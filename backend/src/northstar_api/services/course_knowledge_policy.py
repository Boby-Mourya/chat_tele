"""Pure course knowledge rules: explicit tuples, immutable evidence, scoped units."""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass
from typing import Any, Iterable


class KnowledgePolicyError(ValueError):
    """An inspectable validation failure, not a semantic accuracy estimate."""


def fingerprint(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class Audience:
    tenant_id: str
    workspace_id: str
    agent_id: str
    course_id: str
    curriculum_id: str
    paper_id: str | None = None
    batch_id: str | None = None
    overview: bool = False

    def validate(self) -> None:
        if not all((self.tenant_id, self.workspace_id, self.agent_id, self.course_id, self.curriculum_id)):
            raise KnowledgePolicyError("An explicit tenant/workspace/agent/course/curriculum is required")
        if self.overview != (self.paper_id is None):
            raise KnowledgePolicyError("No paper is allowed only for explicitly reviewed course-overview material")


@dataclass(frozen=True, slots=True)
class LearnerScope:
    tenant_id: str
    workspace_id: str
    agent_id: str
    student_id: str
    enrollment_id: str
    course_id: str
    curriculum_id: str
    batch_id: str
    paper_ids: frozenset[str]
    selected_paper_id: str | None
    authorization_revision: int

    def permits(self, audience: Audience) -> bool:
        try:
            audience.validate()
        except KnowledgePolicyError:
            return False
        return all(getattr(self, k) == getattr(audience, k) for k in ("tenant_id", "workspace_id", "agent_id", "course_id", "curriculum_id")) and (audience.batch_id is None or audience.batch_id == self.batch_id) and (audience.overview or (self.selected_paper_id is not None and self.selected_paper_id in self.paper_ids and audience.paper_id == self.selected_paper_id))


def audience_intersection(audiences: Iterable[Audience]) -> Audience:
    items = list(audiences)
    if not items:
        raise KnowledgePolicyError("Derived material must name its source assignments")
    for item in items:
        item.validate()
    first = items[0]
    if len({(a.tenant_id, a.workspace_id, a.agent_id, a.course_id, a.curriculum_id) for a in items}) != 1:
        raise KnowledgePolicyError("An artifact cannot combine different course/curriculum security boundaries")
    batches = {a.batch_id for a in items if a.batch_id is not None}
    papers = {a.paper_id for a in items if a.paper_id is not None}
    if len(batches) > 1 or len(papers) > 1:
        raise KnowledgePolicyError("The source audiences have no single selected-paper/batch intersection")
    return Audience(first.tenant_id, first.workspace_id, first.agent_id, first.course_id, first.curriculum_id, next(iter(papers), None), next(iter(batches), None), not papers)


def canonical_blocks(record: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    seen = set()
    source_name = str(record.get("source_name", "")).casefold()
    rendered = fingerprint({"source": record.get("source_sha256"), "config": record.get("config_sha256"), "page_images": [p.get("image_sha256") for p in record.get("pages", [])]}) if record.get("word") else None
    for unit_index, page in enumerate(record.get("pages", []), 1):
        raw_blocks = page.get("blocks", [])
        if not raw_blocks and page.get("selected_text"):
            raw_blocks = [{"id": f"U{unit_index:04d}-P{i:06d}", "type": "paragraph", "selected_text": value} for i, value in enumerate(re.split(r"\n\s*\n", page["selected_text"]), 1) if value.strip()]
        for ordinal, raw in enumerate(raw_blocks):
            if raw.get("status") == "split":
                continue
            block_id = str(raw.get("id") or "")
            if not block_id or block_id in seen:
                raise KnowledgePolicyError("Every extracted block must have a unique stable ID")
            seen.add(block_id)
            text = str(raw.get("selected_text") or "")
            unit = page.get("source_unit", "unknown")
            page_number = None
            rendering = page.get("rendered_version_id")
            if unit == "pdf_page" or (source_name.endswith(".pdf") and page.get("source_page_number")):
                page_number = page.get("source_page_number") or page.get("number")
            elif rendering:
                page_number = page.get("number")
            elif rendered and page.get("image_sha256") and page.get("rendered_page_number"):
                page_number, rendering = page["rendered_page_number"], rendered
            result.append({"id": block_id, "text": text, "type": str(raw.get("type", "paragraph")), "unit": unit_index,
                "ordinal": ordinal, "source_unit": unit, "page_number": page_number, "rendered_version_id": rendering,
                "paragraph_reference": raw.get("paragraph_reference") or raw.get("paragraph_index"), "bbox_px": raw.get("bbox_px"),
                "related_block_ids": list(raw.get("related_block_ids") or []),
                "structure": raw.get("reviewed_structure") or raw.get("visual") or raw.get("structure"), "text_hash": fingerprint(text)})
    if not result:
        raise KnowledgePolicyError("No reviewed source blocks are available")
    return result


def text_record(text: str, source_sha: str, revision: int) -> dict[str, Any]:
    blocks = [{"id": f"T{i:06d}", "type": "paragraph", "selected_text": p} for i, p in enumerate(re.split(r"\n\s*\n", text), 1) if p.strip()]
    return {"source_sha256": source_sha, "extraction_revision": revision,
        "pages": [{"number": 1, "source_unit": "text_document", "selected_text": text, "blocks": blocks}],
        "review_status": "native_text_requires_mapping_review", "release_eligible": True}


def selected_blocks(blocks: list[dict[str, Any]], ids: Iterable[str]) -> list[dict[str, Any]]:
    requested = list(ids)
    chosen = set(requested)
    if not chosen or len(chosen) != len(requested):
        raise KnowledgePolicyError("Select distinct source block IDs")
    if not chosen <= {b["id"] for b in blocks}:
        raise KnowledgePolicyError("The mapping references missing source blocks")
    for block in blocks:
        if block["id"] in chosen and not set(block.get("related_block_ids") or []) <= chosen:
            raise KnowledgePolicyError("Include linked question/options/solution blocks or review their relationship first")
    return [b for b in blocks if b["id"] in chosen]


def scoped_chunks(blocks: list[dict[str, Any]], ids: Iterable[str], max_words: int = 2400) -> list[dict[str, Any]]:
    selected = selected_blocks(blocks, ids)
    neighbors = {b["id"]: set(b.get("related_block_ids") or []) for b in selected}
    for block_id, links in list(neighbors.items()):
        for linked in list(links):
            neighbors[linked].add(block_id)
    visited = set()
    chunks = []
    for block in selected:
        if block["id"] in visited:
            continue
        component = set()
        pending = [block["id"]]
        while pending:
            item = pending.pop()
            if item not in component:
                component.add(item)
                pending.extend(neighbors[item] - component)
        visited.update(component)
        group = [b for b in selected if b["id"] in component]
        parts = []
        for item in group:
            parts.append(item["text"])
            structure = item.get("structure") or {}
            retained = {k: structure[k] for k in ("cells", "latex", "option_labels", "printed_answer", "observed_relationships", "figure_labels") if structure.get(k)}
            if not item["text"].strip() and not retained:
                raise KnowledgePolicyError(f"Block {item['id']} has no reviewed text or structured representation; review it before publication")
            if retained:
                parts.append("[REVIEWED SOURCE STRUCTURE]\n" + json.dumps(retained, ensure_ascii=False, sort_keys=True))
        content = "\n\n".join(parts)
        if len(content.split()) > max_words:
            raise KnowledgePolicyError(f"Block {block['id']} is an oversized atomic unit; review and split it before publication")
        references = [{k: b.get(k) for k in ("id", "type", "unit", "source_unit", "page_number", "rendered_version_id", "paragraph_reference")} for b in group]
        chunks.append({"content": content, "block_ids": [b["id"] for b in group], "references": references, "content_hash": fingerprint(content)})
    return chunks


def mapping_fingerprint(source_hash: str, extraction_hash: str, audience: Audience, block_ids: Iterable[str], revision: int, material_type: str, topic_ids: Iterable[str]) -> str:
    audience.validate()
    return fingerprint({"source": source_hash, "extraction": extraction_hash, "audience": asdict(audience), "blocks": sorted(block_ids), "revision": revision, "material_type": material_type, "topics": sorted(topic_ids)})


def mismatch_warnings(title: str, blocks: list[dict[str, Any]], intended_names: list[str], other_courses: list[tuple[str, list[str]]]) -> list[dict[str, str]]:
    texts = [("source_title", title)] + [(b["id"], b["text"]) for b in blocks if b["type"] == "heading"]
    intended = {n.casefold().strip() for n in intended_names}
    warnings = []
    for course_id, aliases in other_courses:
        aliases = [a for a in aliases if len(a.strip()) >= 3 and a.casefold().strip() not in intended]
        for ref, text in texts:
            matches = [a for a in aliases if re.search(r"(?<!\w)" + re.escape(a) + r"(?!\w)", text, flags=re.I)]
            if matches:
                warnings.append({"code": "possible_course_mismatch", "block_id": ref, "suggested_course_id": course_id, "evidence": ", ".join(matches)})
    return warnings


def validate_vectors(vectors: list[list[float]], count: int, dimension: int) -> None:
    if len(vectors) != count:
        raise KnowledgePolicyError("Index preparation returned the wrong number of vectors")
    for vector in vectors:
        if len(vector) != dimension or not all(math.isfinite(float(v)) for v in vector):
            raise KnowledgePolicyError("Index preparation returned an invalid vector")
        if not any(float(v) != 0 for v in vector):
            raise KnowledgePolicyError("Index preparation returned a zero vector")


def extraction_text(title: str, version: int, blocks: list[dict[str, Any]], validation: dict[str, Any]) -> str:
    lines = [f"SOURCE: {title}", f"VERSION: {version}", ""]
    for block in blocks:
        reference = f"Source page {block['page_number']}" if block.get("page_number") else f"Source unit {block['unit']} (not a page citation)"
        lines.extend([f"[{reference} | Block {block['id']} | {block['type']}]", block["text"], ""])
        if block.get("structure"):
            lines.append("STRUCTURE\t" + json.dumps(block["structure"], ensure_ascii=False, sort_keys=True))
    lines.extend(["VALIDATION (not a semantic-accuracy percentage)", json.dumps(validation, indent=2, ensure_ascii=False)])
    return "\n".join(lines)


def explicit_choice(message: str, options: list[tuple[str, list[str]]], *, prefix: str) -> str | None:
    value = re.sub(r"\s+", " ", message.casefold()).strip()
    value = re.sub(rf"^(?:/{prefix}|{prefix}|study|switch to)\s+", "", value)
    value = value.split(":", 1)[0].strip()
    matches = {identity for identity, names in options if value in {re.sub(r"\s+", " ", n.casefold()).strip() for n in names if n}}
    return next(iter(matches)) if len(matches) == 1 else None


def numbered_choice(message: str, menu: list[str], allowed: set[str]) -> str | None:
    value = message.strip()
    if not value.isascii() or not value.isdigit() or len(value) > 3:
        return None
    index = int(value) - 1
    return menu[index] if 0 <= index < len(menu) and menu[index] in allowed else None
