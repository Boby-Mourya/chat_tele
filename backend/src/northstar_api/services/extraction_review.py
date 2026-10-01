"""Versioned human decisions, structure edits, and independent acceptance."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

from northstar_api.services.extraction_schema import Reading, digest
from northstar_api.services.extraction_validation import critical_page, review_digest


def apply_review(
    record: dict[str, Any],
    reviewed_pages: list[dict[str, Any]],
    resolutions: list[dict[str, Any]],
    reviewer: str,
) -> None:
    """Validate a complete transaction before changing the canonical record."""
    candidate = deepcopy(record)
    _apply_review(candidate, reviewed_pages, resolutions, reviewer)
    record.clear()
    record.update(candidate)


def _apply_review(
    record: dict[str, Any],
    reviewed_pages: list[dict[str, Any]],
    resolutions: list[dict[str, Any]],
    reviewer: str,
) -> None:
    if record.get("schema_version") != 2:
        raise ValueError("Retry extraction to create the current evidence schema")
    pages = record["pages"]
    submitted_numbers = [p["number"] for p in reviewed_pages]
    if (
        not submitted_numbers
        or submitted_numbers != sorted(set(submitted_numbers))
        or not set(submitted_numbers) <= {p["number"] for p in pages}
    ):
        raise ValueError("Review unique known source units in source order")
    issues = {issue["id"]: issue for issue in record["issues"]}
    if len({r["id"] for r in resolutions}) != len(resolutions):
        raise ValueError("Duplicate issue decisions")
    now = datetime.now(UTC).isoformat()
    history = record.setdefault("correction_history", [])
    for resolution in resolutions:
        if resolution["id"] not in issues:
            raise ValueError("Unknown issue decision")
        issue = issues[resolution["id"]]
        if issue.get("technical") and resolution["action"] != "unresolved":
            raise ValueError("Technical extraction failures require reprocessing, not reviewer approval")
        if not resolution["reason"].strip():
            raise ValueError("Issue decisions require a source-based reason")
        previous = dict(issue)
        issue.update(
            {
                "status": "open" if resolution["action"] == "unresolved" else "resolved",
                "disposition": resolution["action"],
                "resolution_reason": resolution["reason"],
                "resolved_by": reviewer,
                "resolved_at": now,
            }
        )
        if previous.get("status") != issue["status"] or previous.get("disposition") != issue["disposition"]:
            for page in pages:
                if page["number"] == issue["page"] or issue["page"] == 0:
                    page.pop("primary_review", None)
                    page.pop("second_review", None)
            history.append(
                {
                    "kind": "issue",
                    "id": issue["id"],
                    "before": previous,
                    "after": dict(issue),
                    "reviewer": reviewer,
                    "reviewed_at": now,
                }
            )
    all_ids = {b["id"] for p in pages for b in p.get("blocks", [])}
    page_lookup = {p["number"]: p for p in pages}
    for submitted in reviewed_pages:
        page = page_lookup[submitted["number"]]
        if not submitted["reason"].strip() or not submitted.get("structure_confirmed"):
            raise ValueError("Confirm source coverage, order, structure and relationships for every unit")
        before = review_digest(page)
        old_text = page.get("selected_text")
        leaves = [b for b in page.get("blocks", []) if b.get("status") != "split"]
        edits = submitted.get("blocks", [])
        if [b["id"] for b in edits] != [b["id"] for b in leaves]:
            raise ValueError("Review every leaf region in source reading order")
        for block, edit in zip(leaves, edits, strict=True):
            structure = edit.get("structure") or block.get("visual")
            if structure is None:
                raise ValueError("A region has no successful visual reading; reprocess it")
            structure = Reading.model_validate(structure).model_dump()
            for cell in structure.get("cells", []):
                cell["cell_id"] = f"{block['id']}-R{cell['row']}C{cell['column']}"
            if not structure["complete"]:
                raise ValueError("Incomplete readings require reprocessing")
            if structure["text"] != edit["selected_text"]:
                raise ValueError("Region text must match the reviewed structured text")
            if any(link not in all_ids or link == block["id"] for link in edit.get("related_block_ids", [])):
                raise ValueError("Region relationship references an unknown or identical block")
            if structure.get("uncertain") or "[[UNREADABLE]]" in edit["selected_text"]:
                raise ValueError("Unreadable source cannot be marked reviewed")
            history.append(
                {
                    "kind": "block",
                    "id": block["id"],
                    "before": deepcopy(block),
                    "after_structure": structure,
                    "related_block_ids": edit.get("related_block_ids", []),
                    "reviewer": reviewer,
                    "reviewed_at": now,
                    "reason": submitted["reason"],
                    "evidence": block.get("crop"),
                }
            )
            block.update(
                {
                    "type": structure["kind"],
                    "selected_text": edit["selected_text"],
                    "reviewed_structure": structure,
                    "related_block_ids": edit.get("related_block_ids", []),
                    "structure_reviewed": True,
                }
            )
            if structure.get("continues_from_previous") or structure.get("continues_on_next"):
                if not edit.get("related_block_ids"):
                    raise ValueError("Continued content requires an explicit related source block")
        text = submitted["selected_text"]
        if leaves and "\n".join(b["selected_text"] for b in leaves) != text:
            raise ValueError("Page text must be the exact ordered projection of reviewed regions")
        if not leaves and page.get("source_unit") == "bytes" and text != page["native_text"]:
            raise ValueError("Text-file source bytes are authoritative; source mistakes must be preserved")
        if "[[UNREADABLE]]" in text or (not text and not submitted.get("blank_confirmed") and not leaves):
            raise ValueError("Confirm a blank source explicitly; unreadable text is never verified")
        page["selected_text"] = text
        after = review_digest(page)
        if before != after:
            page.pop("primary_review", None)
            page.pop("second_review", None)
        review = {
            "reviewer": reviewer,
            "reviewed_at": now,
            "reason": submitted["reason"],
            "content_sha256": after,
            "image_sha256": page.get("image_sha256"),
            "source_sha256": record["source_sha256"],
            "structure_confirmed": True,
        }
        primary = page.get("primary_review")
        if primary and primary["content_sha256"] == after and primary["reviewer"] != reviewer:
            page["second_review"] = review
        elif not primary or primary["content_sha256"] != after:
            page["primary_review"] = review
        page["requires_second_review"] = critical_page(page)
        history.append(
            {
                "kind": "page",
                "page": page["number"],
                "reviewer": reviewer,
                "reviewed_at": now,
                "reason": submitted["reason"],
                "previous_text": old_text,
                "selected_text": text,
                "previous_sha256": before,
                "selected_sha256": after,
                "image_sha256": page.get("image_sha256"),
                "structure_sha256": digest(edits),
            }
        )
    record["approved_pages"] = [p["number"] for p in pages if p.get("primary_review")]
    record["review_status"] = "needs_review"
