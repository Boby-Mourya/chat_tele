"""Source-preserving hybrid extraction with bounded NVIDIA reading and review gates."""

from __future__ import annotations

import asyncio
import codecs
import hashlib
import io
import json
import re
import time
import zipfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from importlib.metadata import version
from typing import Any

import fitz
from PIL import Image, ImageOps, ImageSequence
from pypdf import PdfReader

from northstar_api.config import Settings
from northstar_api.services.extraction_regions import (
    PROMPT_VERSION,
    read_page,
    recover_disputes,
    region_artifacts,
)
from northstar_api.services.extraction_schema import digest
from northstar_api.services.extraction_validation import (
    critical_page,
    disagreement,
    metrics,
    same_text,
    validate,
)
from northstar_api.services.extraction_word import inspect_word, render_word
from northstar_api.services.vision import read_image, verify_image_capability

PageCheckpoint = tuple[dict[str, Any], bytes, list[dict[str, Any]]]
PageCallback = Callable[[dict[str, Any], bytes, list[dict[str, Any]]], Awaitable[None]]


def configuration(settings: Settings) -> dict[str, Any]:
    return {key: value for key, value in settings.model_dump().items() if key.startswith("extraction_")}


@dataclass
class ExtractionPackage:
    record: dict[str, Any]
    images: dict[str, bytes]

    @classmethod
    def from_archive(cls, data: bytes, *, source_sha256: str, revision: int) -> ExtractionPackage:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            members = archive.infolist()
            if len(members) > 200_000 or sum(m.file_size for m in members) > 2 * 1024**3:
                raise ValueError("Extraction evidence exceeds archive limits")
            names = [m.filename for m in members]
            manifest = json.loads(archive.read("manifest.json"))
            if len(names) != len(set(names)) or set(names) != set(manifest["artifacts"]) | {"manifest.json"}:
                raise ValueError("Evidence manifest does not account for every artifact")
            artifacts = {}
            for name, expected in manifest["artifacts"].items():
                payload = archive.read(name)
                if hashlib.sha256(payload).hexdigest() != expected:
                    raise ValueError("Extraction evidence checksum failed")
                artifacts[name] = payload
            record = json.loads(artifacts.pop("extracted.json"))
            if record.get("source_sha256") != source_sha256 or manifest.get("source_sha256") != source_sha256:
                raise ValueError("Evidence belongs to a different source")
            if (
                record.get("extraction_revision") != revision
                or manifest.get("extraction_revision") != revision
            ):
                raise ValueError("Evidence revision changed")
            for name in ("extracted_review.txt", "validation_report.txt", "correction_history.json"):
                artifacts.pop(name)
        package = cls(record, artifacts)
        package.refresh()
        return package

    @property
    def issues(self) -> list[dict[str, Any]]:
        return self.record["issues"]

    def refresh(self) -> None:
        self.record["checks"] = validate(self.record, self.images)
        self.record["metrics"] = metrics(self.record)
        passed = all(check["status"] == "PASSED" for check in self.record["checks"])
        self.record["release_eligible"] = passed
        if self.record["review_status"] == "verified_release" and not passed:
            self.record["review_status"] = "needs_review"
        self.record["release_blockers"] = [
            c["name"] for c in self.record["checks"] if c["status"] != "PASSED"
        ]
        self.record["release_decision"] = (
            "VERIFIED_RELEASE" if passed and self.record["review_status"] == "verified_release" else "BLOCKED"
        )
        self.record["export_state"] = (
            "VERIFIED_RELEASE" if self.record["release_decision"] == "VERIFIED_RELEASE" else "EXPORTED_DRAFT"
        )
        pages = self.record["pages"]
        visual_pages = [p for p in pages if p.get("requires_image")]
        self.record["stages"] = [
            {"stage": "inspect", "status": "complete" if pages else "blocked"},
            {"stage": "native_extract", "status": "complete" if pages else "blocked"},
            {
                "stage": "render",
                "status": "not_applicable"
                if not visual_pages
                else "complete"
                if all(p.get("image") for p in visual_pages)
                else "blocked",
            },
            {
                "stage": "visual_inventory",
                "status": "not_applicable"
                if not visual_pages
                else "complete"
                if all(p.get("inventory_complete") for p in visual_pages)
                else "blocked",
            },
            {
                "stage": "region_reading",
                "status": "not_applicable"
                if not visual_pages
                else "complete"
                if all(
                    p.get("inventory_complete")
                    and all(b.get("visual") for b in p.get("blocks", []) if b.get("status") != "split")
                    for p in visual_pages
                )
                else "blocked",
            },
            {"stage": "validate", "status": "complete"},
            {"stage": "human_review", "status": "complete" if passed else "pending"},
            {"stage": "release_decision", "status": self.record["release_decision"]},
        ]
        # Physical fragments remain intact; explicit reviewed continuity supplies logical groups.
        blocks = [b for p in pages for b in p.get("blocks", []) if b.get("status") != "split"]
        groups = {b["id"]: b["id"] for b in blocks}
        by_id = {b["id"]: b for b in blocks}
        for block in blocks:
            structure = block.get("reviewed_structure") or {}
            if not (structure.get("continues_from_previous") or structure.get("continues_on_next")):
                continue
            for ref in block.get("related_block_ids", []):
                if ref in by_id and by_id[ref]["type"] == block["type"]:
                    old, new = groups[ref], groups[block["id"]]
                    groups = {key: new if value == old else value for key, value in groups.items()}
        self.record["logical_groups"] = [
            {"id": "L-" + group, "fragment_ids": [key for key, value in groups.items() if value == group]}
            for group in sorted(set(groups.values()))
        ]

    def review_text(self) -> str:
        self.refresh()
        lines = [
            f"SOURCE SHA-256: {self.record['source_sha256']}",
            f"STATUS: {self.record['review_status'].upper()}",
            "Source strings are JSON-escaped to preserve newlines, delimiters and exact characters.",
        ]
        if self.record.get('word'):
            lines.append('\n[WORD LOGICAL SOURCE — PAGINATION BELONGS TO THE RENDERED DERIVATIVE]')
            for block in self.record['word']['blocks']:
                lines.append(f"[{block['type'].upper()} {block['id']} | {block['part']} | {block.get('channel', 'current')}]")
                lines.append(block['text'])
                if block.get('cells'):
                    lines.append('WORD_TABLE_CELLS\t' + json.dumps(block['cells'], ensure_ascii=False))
            for channel in self.record['word']['channels']:
                lines.append('[SEPARATE WORD CHANNEL] ' + json.dumps(channel, ensure_ascii=False))
        for page in self.record["pages"]:
            lines.extend(
                [
                    f"SOURCE UNIT: {page['number']} ({page.get('source_unit', 'page')})",
                    f"PRINTED PAGE LABEL: {json.dumps(page.get('printed_page_label'), ensure_ascii=False)}",
                    f"IMAGE: {page.get('image') or 'NONE'}",
                ]
            )
            for key in ("native_text", "visual_text", "selected_text"):
                lines.append(f"{key.upper()}: {json.dumps(page.get(key), ensure_ascii=False)}")
            for channel in ('annotations', 'form_fields'):
                for item in page.get(channel, []):
                    lines.append(f'[{channel.upper()} — SOURCE METADATA] ' + json.dumps(item, ensure_ascii=False))
            for block in page.get("blocks", []):
                lines.append(f"\n[{block['type'].upper()} {block['id']} | {block.get('crop', 'NO_CROP')}]")
                if block.get("status") == "split":
                    lines.append("Physical region split into the following source fragments.")
                    continue
                lines.append(
                    block.get("selected_text")
                    if block.get("selected_text") is not None
                    else f"[[UNCERTAIN:{block['id']}]]"
                )
                structure = block.get("reviewed_structure") or block.get("visual") or {}
                for cell in structure.get("cells", []):
                    lines.append(
                        f"  Cell R{cell['row']}C{cell['column']} [{cell.get('state', 'VALUE')}] "
                        f"span {cell.get('row_span', 1)}x{cell.get('column_span', 1)}: "
                        + json.dumps(cell["text"], ensure_ascii=False)
                        + " headers="
                        + json.dumps(cell.get("header_refs", []))
                    )
                for field in (
                    "latex",
                    "printed_label",
                    "printed_caption",
                    "figure_labels",
                    "handwritten_annotation",
                    "observed_relationships",
                    "option_labels",
                    "printed_answer",
                ):
                    if structure.get(field) is not None:
                        lines.append(f"  {field}: " + json.dumps(structure[field], ensure_ascii=False))
                if structure.get("derived_description"):
                    lines.append(
                        "  DERIVED DESCRIPTION — NOT VERBATIM SOURCE: "
                        + json.dumps(structure["derived_description"], ensure_ascii=False)
                    )
                lines.append("BLOCK_RECORD\t" + json.dumps(block, ensure_ascii=False, sort_keys=True))
            if not page.get("blocks"):
                lines.append(
                    "\n[EXACT SOURCE TEXT]\n"
                    + (
                        page.get("selected_text")
                        if page.get("selected_text") is not None
                        else "[[UNRESOLVED]]"
                    )
                )
        for issue in self.issues:
            lines.append("[ISSUE - NOT SOURCE TEXT] " + json.dumps(issue, ensure_ascii=False, sort_keys=True))
        # A lossless tagged record is checked against extracted.json before every export.
        lines.append("CANONICAL_RECORD\t" + json.dumps(self.record, ensure_ascii=False, sort_keys=True))
        return "\n".join(lines) + "\n"

    def validation_text(self) -> str:
        self.refresh()
        lines = [
            f"Source SHA-256: {self.record['source_sha256']}",
            f"Extraction revision: {self.record.get('extraction_revision')}",
            f"Configuration SHA-256: {self.record.get('config_sha256')}",
            f"Expected units: {self.record['expected_units']}",
            f"Processed units: {len(self.record['pages'])}",
            f"Vision model: {self.record.get('vision_model') or 'NOT_RUN'}",
            "Measured accuracy: NOT_MEASURED",
            f"Verified release: {'APPROVED' if self.record['review_status'] == 'verified_release' and self.record['release_eligible'] else 'BLOCKED'}",
        ]
        for check in self.record["checks"]:
            lines.append(
                f"{check['name']}: {check['status']} " + json.dumps(check["details"], ensure_ascii=False)
            )
        for issue in self.issues:
            lines.append(json.dumps(issue, sort_keys=True, ensure_ascii=False))
        return "\n".join(lines) + "\n"

    def archive(self) -> bytes:
        self.refresh()
        report = self.review_text().encode("utf-8")
        validation = self.validation_text().encode("utf-8")
        canonical = json.dumps(self.record, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
        # The final record is authoritative even when the source itself contains tagged-looking lines.
        tagged = report.decode().rsplit("\nCANONICAL_RECORD\t", 1)[-1].rstrip("\n")
        if json.loads(tagged) != json.loads(canonical):
            raise ValueError("Export projection differs from canonical records")
        artifacts = {
            "extracted.json": canonical,
            "extracted_review.txt": report,
            "validation_report.txt": validation,
            "correction_history.json": json.dumps(
                self.record.get("correction_history", []), ensure_ascii=False, sort_keys=True
            ).encode(),
            **self.images,
        }
        manifest = {
            "schema_version": 2,
            "extraction_revision": self.record.get("extraction_revision"),
            "source_sha256": self.record["source_sha256"],
            "prompt_version": PROMPT_VERSION,
            "config_sha256": self.record.get("config_sha256"),
            "parsers": self.record.get("parsers"),
            "vision_model": self.record.get("vision_model"),
            "vision_provider": self.record.get("vision_provider"),
            "expected_units": self.record["expected_units"],
            "artifacts": {name: hashlib.sha256(data).hexdigest() for name, data in artifacts.items()},
        }
        artifacts["manifest.json"] = json.dumps(manifest, sort_keys=True, indent=2).encode()
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, data in sorted(artifacts.items()):
                info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, data)
        return output.getvalue()


def encode_page_checkpoint(
    page: dict[str, Any],
    image: bytes,
    page_issues: list[dict[str, Any]],
    *,
    source_sha256: str,
    model: str,
    version: int,
) -> bytes:
    metadata = {
        "source_sha256": source_sha256,
        "model": model,
        "prompt_version": PROMPT_VERSION,
        "version": version,
        "page": page,
        "issues": page_issues,
        "image_sha256": hashlib.sha256(image).hexdigest(),
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("page.json", json.dumps(metadata, ensure_ascii=False, sort_keys=True))
        archive.writestr("image.png", image)
    return output.getvalue()


def decode_page_checkpoint(
    data: bytes,
    *,
    source_sha256: str,
    model: str,
    version: int,
    page_number: int,
) -> PageCheckpoint:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if len(archive.infolist()) != 2 or sum(m.file_size for m in archive.infolist()) > 128 * 1024**2 or set(archive.namelist()) != {"page.json", "image.png"}:
            raise ValueError("Checkpoint artifact set is invalid")
        metadata = json.loads(archive.read("page.json"))
        image = archive.read("image.png")
    page = metadata.get("page")
    if (
        metadata.get("source_sha256") != source_sha256
        or metadata.get("model") != model
        or metadata.get("prompt_version") != PROMPT_VERSION
        or metadata.get("version") != version
        or not isinstance(page, dict)
        or page.get("number") != page_number
        or metadata.get("image_sha256") != hashlib.sha256(image).hexdigest()
        or page.get("image_sha256") != hashlib.sha256(image).hexdigest()
        or not isinstance(metadata.get("issues"), list)
    ):
        raise ValueError("Checkpoint source identity or checksum failed")
    return page, image, metadata["issues"]


def _compare(native: str, visual: str) -> bool:
    return same_text(native, visual)


def native_page_quality(native: str, details: dict[str, Any]) -> dict[str, Any]:
    """Measure native-text sufficiency before using vision; this is not an accuracy claim."""
    text = native.strip()
    compact = re.sub(r"\s+", "", text)
    letters = sum(character.isalpha() for character in compact)
    words = re.findall(r"\b[\w'-]+\b", text)
    figures = sum(block.get("type") == "figure" for block in details.get("native_blocks", []))
    tables = details.get("native_tables", [])
    formula_like = bool(re.search(r"(?:[=≈≠≤≥∫∑√]|\^|[_][{(]|[A-Za-z]\d)", text))
    reasons: list[str] = []
    if len(compact) < 80 or len(words) < 12:
        reasons.append("very_little_native_text")
    if "�" in text or (compact and letters / len(compact) < 0.35 and not formula_like):
        reasons.append("possible_ocr_or_encoding_error")
    if figures and (len(words) < 80 or figures > 1):
        reasons.append("image_heavy_content")
    if tables:
        reasons.append("table_structure_requires_visual_reading")
    if formula_like:
        reasons.append("formula_structure_requires_visual_reading")
    score = 1.0 - (0.55 if "very_little_native_text" in reasons else 0) - (0.35 if "possible_ocr_or_encoding_error" in reasons else 0) - (0.20 if "image_heavy_content" in reasons else 0) - (0.10 if tables else 0) - (0.10 if formula_like else 0)
    return {
        "score": round(max(0.0, min(1.0, score)), 2), "native_character_count": len(text),
        "native_word_count": len(words), "native_figure_count": figures, "native_table_count": len(tables),
        "formula_detected": formula_like, "reasons": reasons, "vision_required": bool(reasons),
        "review_required": bool(reasons), "method": "native_text" if not reasons else "native_text_then_visual",
    }


async def _read_image(image: bytes, settings: Settings) -> str:
    return await read_image(image, settings)


def text_unit(data: bytes) -> dict[str, Any]:
    encoding, bom = "utf-8", b""
    for marker, codec in [
        (codecs.BOM_UTF32_LE, "utf-32-le"),
        (codecs.BOM_UTF32_BE, "utf-32-be"),
        (codecs.BOM_UTF8, "utf-8"),
        (codecs.BOM_UTF16_LE, "utf-16-le"),
        (codecs.BOM_UTF16_BE, "utf-16-be"),
    ]:
        if data.startswith(marker):
            encoding, bom = codec, marker
            break
    text = data[len(bom) :].decode(encoding, errors="strict")
    offset = len(bom)
    lines = []
    for number, line in enumerate(text.splitlines(keepends=True), 1):
        size = len(line.encode(encoding))
        lines.append({"number": number, "byte_start": offset, "byte_end": offset + size, "text": line})
        offset += size
    endings = re.findall(r"\r\n|\r|\n", text)
    return {
        "number": 1,
        "source_page_index": None,
        "source_page_number": None,
        "rendered_page_number": None,
        "source_unit": "bytes",
        "native_text": text,
        "visual_text": None,
        "selected_text": text,
        "image": None,
        "requires_image": False,
        # Text files have no rendered-page evidence, so retain the existing
        # explicit review path rather than silently changing their release rule.
        "requires_review": True,
        "encoding": encoding,
        "bom_hex": bom.hex(),
        "line_endings": sorted(set(endings)),
        "lines": lines,
        "line_byte_offsets": [line["byte_start"] for line in lines],
        "blocks": [],
        "blank": not text,
        "inventory_complete": True,
    }


def native_pdf(page: Any, scale: float) -> dict[str, Any]:
    blocks = []
    words = []

    def box(value: Any) -> list[int]:
        rect = fitz.Rect(value) * page.rotation_matrix
        return [max(0, round(v * scale)) for v in rect]

    for i, value in enumerate(page.get_text("dict")["blocks"]):
        if value["type"] == 0:
            spans = [span for line in value["lines"] for span in line["spans"]]
            blocks.append(
                {
                    "id": f"N{i:04d}",
                    "type": "text",
                    "bbox_pt": list(value["bbox"]),
                    "bbox_px": box(value["bbox"]),
                    "text": "\n".join("".join(s["text"] for s in line["spans"]) for line in value["lines"]),
                    "spans": spans,
                }
            )
        else:
            blocks.append(
                {
                    "id": f"N{i:04d}",
                    "type": "figure",
                    "bbox_pt": list(value["bbox"]),
                    "bbox_px": box(value["bbox"]),
                    "text": "",
                    "image_sha256": hashlib.sha256(value.get("image", b"")).hexdigest(),
                }
            )
    for word in page.get_text("words"):
        words.append({"bbox_px": box(word[:4]), "text": word[4], "line": [word[5], word[6]]})
    tables = []
    try:
        for table in page.find_tables().tables:
            tables.append(
                {
                    "bbox_px": box(table.bbox),
                    "row_count": table.row_count,
                    "column_count": table.col_count,
                    "rows": table.extract(),
                    "cell_bboxes_pt": table.cells,
                    "header": table.header.names,
                }
            )
        table_error = None
    except Exception as exc:
        table_error = type(exc).__name__
    annotations = [{"type": a.type, "rect": list(a.rect), "info": a.info} for a in page.annots() or []]
    widgets = [
        {"name": w.field_name, "value": w.field_value, "rect": list(w.rect)} for w in page.widgets() or []
    ]
    return {
        "native_blocks": blocks,
        "native_words": words,
        "native_tables": tables,
        "native_table_error": table_error,
        "annotations": annotations,
        "form_fields": widgets,
        "rotation": page.rotation,
        "source_width_pt": page.cropbox.width,
        "source_height_pt": page.cropbox.height,
        'source_cropbox_pt': list(page.cropbox),
        'rotation_matrix': list(page.rotation_matrix),
        "render_scale": scale,
    }


def inside(inner: list[float], outer: list[float]) -> bool:
    return (
        outer[0] <= (inner[0] + inner[2]) / 2 <= outer[2]
        and outer[1] <= (inner[1] + inner[3]) / 2 <= outer[3]
    )


async def extract_document(
    data: bytes,
    filename: str,
    settings: Settings,
    *,
    resume_pages: dict[int, PageCheckpoint] | None = None,
    on_page: PageCallback | None = None,
) -> ExtractionPackage:
    suffix = filename.lower().rsplit(".", 1)[-1]
    if suffix not in {'pdf', 'docx', 'png', 'jpg', 'jpeg', 'tif', 'tiff', 'txt', 'md', 'markdown'}:
        raise ValueError('Unsupported source extension')
    if len(data) > settings.upload_max_bytes:
        raise ValueError("Source exceeds upload size limit")
    source_hash = hashlib.sha256(data).hexdigest()
    pages: list[dict[str, Any]] = []
    artifacts: dict[str, bytes] = {f"source/original.{suffix}": data}
    issues: list[dict[str, Any]] = []
    resume_pages = resume_pages or {}
    config = configuration(settings)
    record: dict[str, Any] = {
        "schema_version": 2,
        "extraction_revision": None,
        "source_name": filename,
        "source_sha256": source_hash,
        "config": config,
        "config_sha256": digest(config),
        "pages": pages,
        "issues": issues,
        "vision_model": settings.extraction_vision_model,
        "vision_provider": "nvidia",
        "review_status": "needs_review",
        "approved_pages": [],
        "correction_history": [],
        "stages": [],
        "parsers": {
            name: version(name)
            for name in ("pymupdf", "pypdf", "python-docx", "pillow", "langchain-nvidia-ai-endpoints")
        },
    }

    def issue(
        number: int, code: str, message: str, block_id: str | None = None, technical: bool = False
    ) -> None:
        issues.append(
            {
                "id": f"I{len(issues) + 1:06d}",
                "page": number,
                "code": code,
                "message": message,
                "block_id": block_id,
                "technical": technical,
                "status": "open",
                "severity": "CRITICAL"
                if technical or code in {"NUMERIC_CONFLICT", "CRITICAL_WORD_CONFLICT"}
                else "REVIEW",
            }
        )

    def failed_source(exc: Exception, expected_units: int = 0) -> ExtractionPackage:
        record['expected_units'] = expected_units
        record['source_inventory_complete'] = False
        record['review_status'] = 'failed'
        issue(0, 'SOURCE_PARSE_FAILED', f'Source inventory or parsing failed ({type(exc).__name__}); original bytes are preserved', technical=True)
        package = ExtractionPackage(record, artifacts)
        package.refresh()
        return package

    async def process(number: int, image: bytes, native: str, details: dict[str, Any]) -> None:
        start = len(issues)
        started = time.monotonic()
        if number in resume_pages:
            saved, saved_image, saved_issues = resume_pages[number]
            if saved.get("config_sha256") != record["config_sha256"]:
                raise ValueError("Checkpoint configuration changed; retry as a new extraction revision")
            page = saved
            image = saved_image
            if saved.get("vision_capability"):
                record.setdefault("vision_capability", saved["vision_capability"])
            for value in saved_issues:
                issues.append({**value, "id": f"I{len(issues) + 1:06d}"})
        else:
            with Image.open(io.BytesIO(image)) as bitmap:
                width, height = bitmap.size
            quality = native_page_quality(native, details)
            page = {
                "number": number,
                "source_page_index": number - 1,
                "source_page_number": number,
                "rendered_page_number": number,
                "printed_page_label": None,
                "source_unit": "page",
                "native_text": native,
                "image": f"pages/page_{number:04d}.png",
                "image_sha256": hashlib.sha256(image).hexdigest(),
                "width_px": width,
                "height_px": height,
                # The rendered source image is always retained as evidence, but
                # vision is used only when native text is poor or structure needs it.
                "requires_image": quality["vision_required"],
                "requires_review": quality["review_required"],
                "quality": quality,
                "selected_text": native.strip() if not quality["vision_required"] else None,
                "visual_text": None,
                "blocks": [],
                "inventory_complete": not quality["vision_required"],
                "config_sha256": record["config_sha256"],
                **details,
            }
            if quality["vision_required"] and "vision_capability" not in record:
                probe, pixels = await verify_image_capability(settings)
                record["vision_capability"] = probe
                artifacts["capability/image.png"] = pixels
                artifacts["capability/result.json"] = json.dumps(probe, sort_keys=True).encode()
            if quality["vision_required"]:
                page["vision_capability"] = record["vision_capability"]
                if record["vision_capability"]["status"] == "PASSED":
                    visual = await read_page(image, number, settings)
                else:
                    visual = {
                        "blocks": [], "vision_attempts": [], "visual_text": "", "inventory_complete": False,
                        "problems": [{"code": "VISION_CAPABILITY_FAILED", "message": "NVIDIA image-content capability probe failed", "technical": True}],
                    }
                for problem in visual.pop("problems"):
                    issue(number, **problem)
                page.update(visual)
                if page.get("visual_text"):
                    page["quality"]["method"] = "native_text_plus_vision"
            for reason in quality["reasons"]:
                issue(number, "LOW_EXTRACTION_QUALITY", f"Page quality signal: {reason}")
            page["coordinate_system"] = "rendered_image_pixels_top_left"
            page["transform_id"] = digest(
                {
                    "source": source_hash,
                    "page": number,
                    "rotation": page.get("rotation", 0),
                    "scale": page.get("render_scale", 1),
                    "dimensions": [width, height],
                }
            )
            leaves = [b for b in page["blocks"] if b["status"] != "split"]
            for block in page['blocks']:
                if page.get('source_unit') == 'word_rendered_page':
                    block['source_page_number'] = None
                    block['rendered_page_number'] = number
                    block['source_fragments'] = [{'rendered_page': number, 'derivative': 'derivatives/rendered.pdf', 'bbox_px': block['bbox_px']}]
                block["transform_id"] = page["transform_id"]
                if block['status'] == 'split':
                    continue
                selected_words = [
                    w for w in page.get("native_words", []) if inside(w["bbox_px"], block["bbox_px"])
                ]
                block["native_text"] = " ".join(w["text"] for w in selected_words)
                reading = block.get("visual")
                if reading:
                    block["original_printed_label"] = reading.get("printed_label")
                    for cell in reading.get("cells", []):
                        cell["cell_id"] = f"{block['id']}-R{cell['row']}C{cell['column']}"
                    block["agreement"] = bool(block["native_text"]) and same_text(
                        block["native_text"], reading["text"]
                    )
                    if block["agreement"]:
                        block["selected_text"] = reading["text"]
                    elif block["native_text"]:
                        issue(
                            number,
                            disagreement(block["native_text"], reading["text"]),
                            "Native and visual region candidates differ",
                            block["id"],
                        )
                block["requires_second_review"] = block["type"] in {
                    "table",
                    "equation",
                    "question",
                    "answer_key",
                }
            if page["requires_image"]:
                for native_block in page.get("native_blocks", []):
                    if not any(inside(native_block["bbox_px"], b["bbox_px"]) for b in leaves):
                        issue(
                            number,
                            "NATIVE_REGION_UNACCOUNTED",
                            f"Native object {native_block['id']} is absent from the visual inventory",
                        )
            if page.get("visual_text") and native and not same_text(native, page["visual_text"]):
                issue(
                    number,
                    disagreement(native, page["visual_text"]),
                    "Whole-page native and visual transcripts disagree; inspect reading order and coverage",
                )
            if page.get("native_table_error"):
                issue(
                    number,
                    "NATIVE_TABLE_CHECK_FAILED",
                    "Native table inspection failed; inspect all table structures",
                )
            for table in page.get("native_tables", []):
                candidates = [
                    b for b in leaves if b["type"] == "table" and inside(table["bbox_px"], b["bbox_px"])
                ]
                if not candidates:
                    issue(number, "TABLE_STRUCTURE_UNKNOWN", "Native table has no matching visual table")
                else:
                    cells = (candidates[0].get("visual") or {}).get("cells", [])
                    for r, row in enumerate(table["rows"]):
                        for c, value in enumerate(row):
                            if value is not None and not any(
                                cell["row"] == r and cell["column"] == c and same_text(value, cell["text"])
                                for cell in cells
                            ):
                                issue(
                                    number,
                                    "TABLE_CELL_CONFLICT",
                                    f"Native table cell row {r + 1}, column {c + 1} differs from visual cell",
                                    candidates[0]["id"],
                                )
            for i, left in enumerate(leaves):
                for right in leaves[i + 1 :]:
                    a, b = left["bbox_px"], right["bbox_px"]
                    overlap = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(
                        0, min(a[3], b[3]) - max(a[1], b[1])
                    )
                    if overlap > 0.1 * min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1])):
                        issue(
                            number, "REGION_OVERLAP", f"Visual regions {left['id']} and {right['id']} overlap"
                        )
            if leaves and all(b.get("selected_text") is not None for b in leaves):
                page["selected_text"] = "\n".join(b["selected_text"] for b in leaves)
            elif page.get("blank") and not native:
                page["selected_text"] = ""
            page["requires_second_review"] = critical_page(page) and page["requires_review"]
            disputed = {
                i["block_id"] for i in issues[start:] if i.get("block_id") and "CONFLICT" in i["code"]
            }
            if page["requires_image"]:
                await recover_disputes(
                    page, image, disputed, settings,
                    settings.extraction_page_timeout_seconds - (time.monotonic() - started),
                )
            page["requires_review"] = bool(page["requires_review"] or issues[start:])
            if page["requires_review"] and not issues[start:]:
                issue(
                    number,
                    "SOURCE_REVIEW_REQUIRED",
                    "Compare all source content and region boundaries before approval",
                )
        pages.append(page)
        artifacts[page["image"]] = image
        for name, payload in region_artifacts(page, image).items():
            if sum(map(len, artifacts.values())) + len(payload) > settings.extraction_max_evidence_bytes:
                if not any(i["code"] == "EVIDENCE_LIMIT" for i in issues[start:]):
                    issue(
                        number,
                        "EVIDENCE_LIMIT",
                        "Evidence size limit exceeded; source preserved, release blocked",
                        technical=True,
                    )
                break
            artifacts[name] = payload
        if on_page:
            await on_page(page, image, issues[start:])

    record["stages"].append({"stage": "inspect", "status": "complete"})
    word = None
    if suffix == "docx":
        try:
            word, derivative = inspect_word(data, settings)
        except Exception as exc:
            return failed_source(exc)
        record["word"] = word
        artifacts["derivatives/frozen.docx"] = derivative
        try:
            if word["render_blockers"]:
                raise ValueError("WORD_UNSAFE_RENDER_DEPENDENCY")
            rendered_data, renderer = await asyncio.to_thread(render_word, derivative, settings)
            record["word"]["renderer"] = renderer
            artifacts["derivatives/rendered.pdf"] = rendered_data
            pdf_data = rendered_data
        except Exception as exc:
            issue(
                1,
                "WORD_RENDER_REQUIRED",
                f"Controlled Word rendering unavailable ({type(exc).__name__})",
                technical=True,
            )
            native = "\n".join(
                b["text"]
                for b in word["blocks"]
                if b["part"] == "word/document.xml" and b["type"] == "paragraph"
            )
            pages.append(
                {
                    "number": 1,
                    "source_page_number": None,
                    "source_page_index": None,
                    "rendered_page_number": None,
                    "source_unit": "logical_document",
                    "native_text": native,
                    "visual_text": None,
                    "selected_text": None,
                    "requires_image": True,
                    "image": None,
                    "blocks": [],
                    "inventory_complete": False,
                }
            )
            pdf_data = None
    elif suffix == "pdf":
        pdf_data = data
    else:
        pdf_data = None
    if pdf_data is not None:
        try:
            reader = PdfReader(io.BytesIO(pdf_data))
            if not reader.is_encrypted:
                count = len(reader.pages)
                with fitz.open(stream=pdf_data, filetype='pdf') as inspected:
                    if len(inspected) != count:
                        raise ValueError('PDF parser page count disagreement')
        except Exception as exc:
            return failed_source(exc)
        if reader.is_encrypted:
            record["review_status"] = "needs_password"
            record["expected_units"] = 0
            issue(0, "NEEDS_PASSWORD", "Supply a source unlocked with its password", technical=True)
        else:
            count = len(reader.pages)
            if count > settings.knowledge_max_pdf_pages:
                return failed_source(ValueError('Source exceeds page limit'), count)
            record["expected_units"] = count
            with fitz.open(stream=pdf_data, filetype="pdf") as document:
                if len(document) != count:
                    raise ValueError("PDF parsers disagree about page count")
                labels = reader.page_labels
                for index, page in enumerate(document):
                    number = index + 1
                    if number in resume_pages:
                        await process(number, resume_pages[number][1], "", {})
                        continue
                    if sum(map(len, artifacts.values())) > settings.extraction_max_evidence_bytes:
                        issue(
                            number, "EVIDENCE_LIMIT", "Configured evidence size limit reached", technical=True
                        )
                        pages.append(
                            {
                                "number": number,
                                "native_text": "",
                                "visual_text": None,
                                "selected_text": None,
                                "image": None,
                                "requires_image": True,
                                "blocks": [],
                                "inventory_complete": False,
                            }
                        )
                        continue
                    scale = min(
                        settings.extraction_render_dpi / 72,
                        (settings.extraction_max_image_pixels / max(1, page.rect.width * page.rect.height))
                        ** 0.5,
                    )
                    image = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False).tobytes("png")
                    native = reader.pages[index].extract_text() or ""
                    details = native_pdf(page, scale)
                    details["pdf_page_label"] = labels[index] if index < len(labels) else None
                    details["source_unit"] = "word_rendered_page" if word else "pdf_page"
                    if word:
                        details['source_page_number'] = None
                        details['source_page_index'] = None
                    await process(number, image, native, details)
    elif suffix in {"png", "jpg", "jpeg", "tif", "tiff"}:
        try:
            image_source = Image.open(io.BytesIO(data))
        except Exception as exc:
            return failed_source(exc)
        with image_source as original:
            count = getattr(original, "n_frames", 1)
            if count > settings.knowledge_max_pdf_pages:
                return failed_source(ValueError('Image frame limit'), count)
            record["expected_units"] = count
            for index, frame in enumerate(ImageSequence.Iterator(original)):
                if frame.width * frame.height > 100_000_000:
                    raise ValueError("Image source exceeds pixel limit")
                original_size = list(frame.size)
                source_orientation = frame.getexif().get(274, 1)
                oriented = ImageOps.exif_transpose(frame).convert("RGB")
                oriented_size = list(oriented.size)
                ratio = min(
                    1.0, (settings.extraction_max_image_pixels / (oriented.width * oriented.height)) ** 0.5
                )
                if ratio < 1:
                    oriented = oriented.resize(
                        (max(1, round(oriented.width * ratio)), max(1, round(oriented.height * ratio)))
                    )
                output = io.BytesIO()
                oriented.save(output, format="PNG")
                await process(
                    index + 1,
                    output.getvalue(),
                    "",
                    {
                        "source_unit": "image_frame",
                        "source_frame_index": index,
                        "original_dimensions_px": original_size,
                        'oriented_dimensions_px': oriented_size,
                        'source_exif_orientation': source_orientation,
                        "exif_orientation_applied": True,
                        "render_scale": ratio,
                    },
                )
    elif suffix in {"txt", "md", "markdown"}:
        record["expected_units"] = 1
        record["vision_model"] = None
        record["vision_provider"] = None
        try:
            pages.append(text_unit(data))
        except UnicodeDecodeError:
            issue(
                1,
                "ENCODING_REQUIRED",
                "Strict decoding failed; supply a UTF-8 or BOM-labelled UTF-16/32 source",
                technical=True,
            )
            pages.append(
                {
                    "number": 1,
                    "source_unit": "bytes",
                    "native_text": "",
                    "visual_text": None,
                    "selected_text": None,
                    "requires_image": False,
                    "image": None,
                    "blocks": [],
                }
            )
    elif suffix != "docx":
        raise ValueError("Unsupported source extension")
    record.setdefault("expected_units", len(pages))
    if word and pdf_data:
        for block in word["blocks"]:
            text = re.sub(r"\s+", " ", block["text"]).strip()
            matches = [p["number"] for p in pages if text and text in re.sub(r"\s+", " ", p["native_text"])]
            block["rendered_pages"] = matches
            block["mapping_status"] = "matched" if len(matches) == 1 else "ambiguous"
            if (
                block["part"] == "word/document.xml"
                and block["type"] == "paragraph"
                and text
                and len(matches) != 1
            ):
                issue(
                    matches[0] if matches else 1,
                    "WORD_MAPPING_AMBIGUOUS",
                    f"Logical block {block['id']} needs source-to-page mapping review",
                )
    for page in pages:
        for block in page.get("blocks", []):
            reading = block.get("visual") or {}
            if reading.get("continues_from_previous") or reading.get("continues_on_next"):
                issue(
                    page["number"],
                    "CONTINUITY_REVIEW",
                    "Confirm the linked source fragments across pages",
                    block["id"],
                )
    if (
        sum(len(p.get("native_text", "")) + len(p.get("visual_text") or "") for p in pages)
        > settings.knowledge_max_extracted_characters
    ):
        issue(0, "TEXT_LIMIT", "Extracted candidates exceed configured text limit", technical=True)
    record["stages"].extend(
        [
            {"stage": name, "status": "complete"}
            for name in ("native_extract", "render", "visual_inventory", "region_reading", "reconcile")
        ]
    )
    record["review_status"] = (
        "needs_review" if any(page.get("requires_review") for page in pages) else "verified_release"
    )
    record["stages"].append({"stage": "human_review", "status": "pending" if record["review_status"] == "needs_review" else "not_required"})
    package = ExtractionPackage(record, artifacts)
    package.refresh()
    return package
