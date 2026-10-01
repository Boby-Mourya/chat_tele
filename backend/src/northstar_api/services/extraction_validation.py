"""Deterministic checks; agreement and coverage are never reported as accuracy."""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from typing import Any

from northstar_api.services.extraction_schema import Cell, digest

CRITICAL = re.compile(r"\d|\b(?:NOT|EXCEPT|least|most|incorrect)\b|[=<>\u2264\u2265\u00b2\u2082]", re.I)


def same_text(left: str, right: str) -> bool:
    return re.sub(r"\s+", " ", left).strip() == re.sub(r"\s+", " ", right).strip()


def disagreement(native: str, visual: str) -> str:
    if re.findall(r"[-+\u2212]?\d+(?:[.,]\d+)*", native) != re.findall(r"[-+\u2212]?\d+(?:[.,]\d+)*", visual):
        return "NUMERIC_CONFLICT"
    if re.findall(r"\b(?:NOT|EXCEPT|least|most|incorrect)\b", native, re.I) != re.findall(
        r"\b(?:NOT|EXCEPT|least|most|incorrect)\b", visual, re.I
    ):
        return "CRITICAL_WORD_CONFLICT"
    return "CANDIDATE_CONFLICT"


def critical_page(page: dict[str, Any]) -> bool:
    return bool(
        CRITICAL.search(
            page.get("native_text", "") + (page.get("visual_text") or "") + (page.get("selected_text") or "")
        )
    ) or any(
        block["type"] in {"table", "equation", "question", "answer_key"} for block in page.get("blocks", [])
    )


def review_digest(page: dict[str, Any]) -> str:
    return digest(
        {
            "number": page["number"],
            "image": page.get("image_sha256"),
            "selected_text": page.get("selected_text"),
            "blocks": [
                {
                    "id": b["id"],
                    "selected_text": b.get("selected_text"),
                    "type": b.get("type"),
                    "bbox_px": b.get("bbox_px"),
                    'crop_sha256': b.get('crop_sha256'),
                    "related_block_ids": b.get("related_block_ids", []),
                    "structure_reviewed": b.get("structure_reviewed", False),
                    "reviewed_structure": b.get("reviewed_structure"),
                }
                for b in page.get("blocks", [])
            ],
        }
    )


def table_errors(cells: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    occupied: dict[tuple[int, int], str] = {}
    headers = {f"R{c.get('row')}C{c.get('column')}" for c in cells if c.get("header")}
    if not cells:
        return ["Table has no cells"]
    if any(c.get("row_span", 1) * c.get("column_span", 1) > 10000 for c in cells):
        return ["Table spans exceed safe grid limits"]
    for value in cells:
        try:
            cell = Cell.model_validate(value)
        except ValueError:
            errors.append("Invalid cell schema")
            continue
        key = f"R{cell.row}C{cell.column}"
        if cell.state in {"UNREADABLE", "AMBIGUOUS", "STRUCTURE_UNKNOWN"}:
            errors.append(f"{key}: unresolved cell")
        if cell.state == "BLANK" and cell.text:
            errors.append(f"{key}: blank cell contains text")
        if cell.state == "VALUE" and not cell.text:
            errors.append(f"{key}: value cell has no value")
        if headers and not cell.header and cell.state == "VALUE" and not cell.header_refs:
            errors.append(f"{key}: header associations require review")
        if cell.state == "COVERED_BY_MERGE":
            if cell.text or cell.row_span != 1 or cell.column_span != 1:
                errors.append(f"{key}: covered position cannot contain a value or span")
            continue
        for row in range(cell.row, cell.row + cell.row_span):
            for column in range(cell.column, cell.column + cell.column_span):
                if (row, column) in occupied:
                    errors.append(f"{key}: overlapping span")
                occupied[row, column] = key
        if any(ref not in headers for ref in cell.header_refs):
            errors.append(f"{key}: unknown header reference")
    if occupied:
        rows = max(r for r, _ in occupied) + 1
        cols = max(c for _, c in occupied) + 1
        if rows * cols != len(occupied):
            errors.append("Table grid has unaccounted positions")
    for cell in cells:
        if cell.get("state") == "COVERED_BY_MERGE":
            position = (cell.get("row"), cell.get("column"))
            if position not in occupied or occupied[position] == f"R{position[0]}C{position[1]}":
                errors.append("Covered position has no spanning cell")
    return errors


def validate(record: dict[str, Any], artifacts: dict[str, bytes]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    pages = record.get("pages", [])
    issues = record.get("issues", [])
    open_issues = [i for i in issues if i.get("status") != "resolved"]

    def check(name: str, errors: list[str], pending: bool = False) -> None:
        checks.append(
            {
                "name": name,
                "status": "FAILED" if errors else "NOT_RUN" if pending else "PASSED",
                "details": errors,
                "method": "deterministic" if name != "human_acceptance" else "source_review",
            }
        )

    integrity = []
    originals = [data for name, data in artifacts.items() if name.startswith("source/original.")]
    if len(originals) != 1 or hashlib.sha256(originals[0]).hexdigest() != record.get("source_sha256"):
        integrity.append("Preserved source is missing or its checksum differs")
    if not pages or len(pages) != record.get("expected_units"):
        integrity.append("Expected source unit count does not match processed units")
    if [p["number"] for p in pages] != list(range(1, record.get("expected_units", 0) + 1)):
        integrity.append("Source units are missing, duplicated or out of order")
    for page in pages:
        if page.get("requires_image") and not page.get("image"):
            integrity.append(f"Page {page['number']}: rendering missing")
        if page.get("image") and hashlib.sha256(artifacts.get(page["image"], b"")).hexdigest() != page.get(
            "image_sha256"
        ):
            integrity.append(f"Page {page['number']}: image missing or checksum mismatch")
    check("source_render_integrity", integrity)

    identities = []
    ids = [b["id"] for p in pages for b in p.get("blocks", [])]
    if len(ids) != len(set(ids)):
        identities.append("Duplicate block IDs")
    for page in pages:
        for block in page.get("blocks", []):
            if block.get("source_page_number") != page.get('source_page_number', page['number']):
                identities.append(f"{block['id']}: incorrect source page")
            box = block.get("bbox_px")
            if box and not (
                0 <= box[0] < box[2] <= page["width_px"] and 0 <= box[1] < box[3] <= page["height_px"]
            ):
                identities.append(f"{block['id']}: invalid coordinates")
            if block.get("crop") and block["crop"] not in artifacts:
                identities.append(f"{block['id']}: crop missing")
            elif block.get('crop') and hashlib.sha256(artifacts[block['crop']]).hexdigest() != block.get('crop_sha256'):
                identities.append(f"{block['id']}: crop checksum differs")
            if any(ref not in ids or ref == block["id"] for ref in block.get("related_block_ids", [])):
                identities.append(f"{block['id']}: invalid relationship")
    check("schema_identity", identities)
    coverage = [
        f"Page {p['number']}: visual inventory incomplete"
        for p in pages
        if p.get("requires_image") and not p.get("inventory_complete")
    ]
    coverage += [
        i["id"]
        for i in open_issues
        if i["code"] in {"NATIVE_REGION_UNACCOUNTED", "VISUAL_INVENTORY_FAILED", "REGION_OVERLAP"}
    ]
    check("coverage_reconciliation", coverage)
    check(
        "text_comparison",
        [i["id"] for i in open_issues if "CONFLICT" in i["code"] or i["code"] == "UNREADABLE_SOURCE"],
    )

    tables, educational, continuity = [], [], []
    by_id = {b["id"]: (p, b) for p in pages for b in p.get("blocks", [])}
    for page in pages:
        for block in page.get("blocks", []):
            structure = block.get("reviewed_structure") or block.get("visual") or {}
            if block.get("status") == "split":
                continue
            if not structure.get("complete") or block.get("selected_text") is None:
                educational.append(f"{block['id']}: incomplete source reading or selection")
            if structure.get("kind") != block["type"]:
                educational.append(f"{block['id']}: block type differs from structured reading")
            for relation in structure.get("relationships", []):
                target = by_id.get(relation["target_id"])
                if not target or relation["target_id"] == block["id"]:
                    educational.append(f"{block['id']}: broken {relation['kind']} relationship")
                elif relation["kind"] == "answer_for" and target[1]["type"] != "question":
                    educational.append(f"{block['id']}: printed answer does not link to a question")
                elif relation["kind"] == "caption_of" and target[1]["type"] not in {
                    "figure",
                    "table",
                    "equation",
                }:
                    educational.append(f"{block['id']}: caption target is not an illustration")
            required_relation = {"caption": "caption_of", "answer_key": "answer_for"}.get(block["type"])
            if required_relation and not any(
                r["kind"] == required_relation for r in structure.get("relationships", [])
            ):
                educational.append(f"{block['id']}: source-based {required_relation} link missing")
            if structure.get("options"):
                labels = [option["label"] for option in structure["options"]]
                if labels != structure.get("option_labels"):
                    educational.append(f"{block['id']}: question option labels or order differ")
                for option in structure["options"]:
                    if option["text"] not in structure.get("text", ""):
                        educational.append(f"{block['id']}: option text missing from transcription")
            if block['type'] == 'question':
                visible_labels = re.findall(r'^\s*\(?([A-Za-z])\s*[.)]\s+', structure.get('text', ''), re.M)
                if visible_labels and visible_labels != structure.get('option_labels', []):
                    educational.append(f"{block['id']}: visible option labels are missing or reordered")
                if structure.get('option_labels') and not structure.get('options'):
                    educational.append(f"{block['id']}: structured question options missing")
            if block['type'] == 'equation' and not structure.get('latex'):
                educational.append(f"{block['id']}: equation representation missing")
            if block["type"] == "table" and block.get("status") != "split":
                tables.extend(f"{block['id']}: {e}" for e in table_errors(structure.get("cells", [])))
            if structure.get("uncertain") or "[[UNREADABLE]]" in (block.get("selected_text") or ""):
                educational.append(f"{block['id']}: uncertainty remains")
            if block["type"] in {"equation", "question", "answer_key", "figure"} and not block.get(
                "structure_reviewed"
            ):
                educational.append(f"{block['id']}: source structure needs review")
            for direction, delta in [("continues_from_previous", -1), ("continues_on_next", 1)]:
                if structure.get(direction) and not any(
                    ref in by_id
                    and by_id[ref][0]["number"] == page["number"] + delta
                    and by_id[ref][1]["type"] == block["type"]
                    for ref in block.get("related_block_ids", [])
                ):
                    continuity.append(f"{block['id']}: missing adjacent source fragment")
    check("tables_numbers", tables + [i["id"] for i in open_issues if i["code"] == "NUMERIC_CONFLICT"])
    check("educational_structure", educational)
    check(
        "visual_audit",
        [i["id"] for i in open_issues if i.get("technical")],
        pending=any(p.get("requires_review") and not p.get("primary_review") for p in pages),
    )
    check(
        "document_continuity",
        continuity
        + [
            i["id"]
            for i in open_issues
            if i["code"] in {"CONTINUITY_REVIEW", "SPLIT_BOUNDARY_REVIEW", "WORD_MAPPING_AMBIGUOUS"}
        ],
    )

    projections = []
    for page in pages:
        if page.get("selected_text") is None:
            projections.append(f"Page {page['number']}: no selected transcription")
        if page.get("source_unit") == "bytes" and page.get("selected_text") != page.get("native_text"):
            projections.append(f"Page {page['number']}: source bytes were changed")
        if page.get("selected_text") is not None and page.get("blocks"):
            values = [b.get("selected_text") for b in page["blocks"] if b.get("status") != "split"]
            if any(v is None for v in values) or "\n".join(v or "" for v in values) != page["selected_text"]:
                projections.append(f"Page {page['number']}: selected blocks differ from page text")
    check("export_consistency", projections)
    reviews = []
    for page in pages:
        if not page.get("requires_review"):
            continue
        primary, second = page.get("primary_review"), page.get("second_review")
        expected = review_digest(page)
        if (
            not primary
            or primary.get("content_sha256") != expected
            or primary.get("source_sha256") != record["source_sha256"]
        ):
            reviews.append(f"Page {page['number']}: primary source review missing or stale")
        if critical_page(page) and (
            not second
            or second.get("content_sha256") != expected
            or second.get("source_sha256") != record["source_sha256"]
            or not primary
            or second.get("reviewer") == primary.get("reviewer")
        ):
            reviews.append(f"Page {page['number']}: independent second review missing or stale")
    reviews.extend(f"{i['id']}: unresolved {i['code']}" for i in open_issues)
    check("human_acceptance", reviews)
    return checks


def metrics(record: dict[str, Any]) -> dict[str, Any]:
    pages = record["pages"]
    blocks = [b for p in pages for b in p.get("blocks", []) if b.get("status") != "split"]
    return {
        "expected_units": record["expected_units"],
        "processed_units": len(pages),
        "detected_regions": len(blocks),
        "regions_read": sum(bool(b.get("visual")) for b in blocks),
        "candidate_agreements": sum(b.get("agreement", False) for b in blocks),
        "primary_reviews": sum(bool(p.get("primary_review")) for p in pages),
        "second_reviews": sum(bool(p.get("second_review")) for p in pages),
        "measured_transcription_accuracy": "NOT_MEASURED",
        "issue_counts": dict(Counter(i["code"] for i in record["issues"] if i.get("status") != "resolved")),
    }
