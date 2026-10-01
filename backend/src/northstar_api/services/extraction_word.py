"""OOXML inventory and a recorded, field-frozen Word rendering derivative."""

from __future__ import annotations

import hashlib
import io
import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from lxml import etree

from northstar_api.config import Settings

NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "m": "http://schemas.openxmlformats.org/officeDocument/2006/math",
}
W = "{" + NS["w"] + "}"


def xml(data: bytes) -> Any:
    return etree.fromstring(data, parser=etree.XMLParser(resolve_entities=False, no_network=True))


def visible_text(element: Any) -> str:
    values: list[str] = []
    for node in element.iter():
        if any(parent.tag in {W + "del", W + "moveFrom"} for parent in node.iterancestors()):
            continue
        run = next((a for a in node.iterancestors() if a.tag == W + "r"), None)
        if run is not None:
            hidden = run.find("w:rPr/w:vanish", NS)
            if hidden is not None and hidden.get(W + "val", "true") not in {"0", "false", "off"}:
                continue
        if node.tag in {W + "t", "{" + NS["m"] + "}t"}:
            values.append(node.text or "")
        elif node.tag == W + "tab":
            values.append("\t")
        elif node.tag in {W + "br", W + "cr"}:
            values.append("\n")
    return "".join(values)


def inspect_word(data: bytes, settings: Settings) -> tuple[dict[str, Any], bytes]:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        members = archive.infolist()
        if (
            len(members) > 5000
            or sum(m.file_size for m in members) > settings.knowledge_max_docx_uncompressed_bytes
        ):
            raise ValueError("DOCX exceeds expanded-size or part limit")
        if len({m.filename for m in members}) != len(members):
            raise ValueError("DOCX contains duplicate parts")
        content = {m.filename: archive.read(m) for m in members}
    if "word/document.xml" not in content:
        raise ValueError("DOCX has no main document")
    record: dict[str, Any] = {
        "parts": [],
        "blocks": [],
        "channels": [],
        "render_blockers": [],
        "relationships": [],
        "field_policy": "freeze_cached_values",
        "revision_view": "current_insertions_without_deletions",
    }
    for name, payload in content.items():
        record["parts"].append(
            {"name": name, "sha256": hashlib.sha256(payload).hexdigest(), "size": len(payload)}
        )
        if "vbaproject" in name.lower() or name.startswith("word/embeddings/"):
            record["render_blockers"].append("Active or embedded document content")
        if name.endswith(".rels"):
            root = xml(payload)
            for relation in root:
                attrs = dict(relation.attrib)
                record["relationships"].append({"part": name, **attrs})
                if attrs.get("TargetMode") == "External" and not attrs.get("Type", "").endswith("/hyperlink"):
                    record["render_blockers"].append("External document dependency")
        if not name.startswith("word/") or not name.endswith(".xml"):
            continue
        root = xml(payload)
        if root.getroottree().docinfo.doctype:
            raise ValueError("OOXML must not contain a document type declaration")
        # Preserve every logical part, including notes, comments, styles, numbering and settings.
        for element in root.iter():
            if element.tag not in {W + "p", W + "tbl", "{" + NS["m"] + "}oMath"}:
                continue
            index = len(record["blocks"]) + 1
            kind = (
                "table"
                if element.tag == W + "tbl"
                else "equation"
                if element.tag.endswith("}oMath")
                else "paragraph"
            )
            block: dict[str, Any] = {
                "id": f"W{index:06d}",
                "part": name,
                "type": kind,
                "xpath": root.getroottree().getpath(element),
                "text": visible_text(element),
                "xml": etree.tostring(element, encoding="unicode"),
                "rendered_pages": [],
                "mapping_status": "unmapped",
            }
            block["parent_xpath"] = (
                root.getroottree().getpath(element.getparent()) if element.getparent() is not None else None
            )
            block["channel"] = (
                "comments"
                if "comments" in name
                else "deleted"
                if any(a.tag in {W + "del", W + "moveFrom"} for a in element.iterancestors())
                else "current"
            )
            block["style"] = element.xpath("string(w:pPr/w:pStyle/@w:val)", namespaces=NS)
            block["numbering"] = element.xpath("string(w:pPr/w:numPr/w:numId/@w:val)", namespaces=NS)
            if kind == "table":
                cells = []
                for r, row in enumerate(element.findall("w:tr", NS)):
                    column = 0
                    for cell in row.findall("w:tc", NS):
                        span = cell.find("w:tcPr/w:gridSpan", NS)
                        span_value = int(span.get(W + "val", "1")) if span is not None else 1
                        merge = cell.find("w:tcPr/w:vMerge", NS)
                        cells.append(
                            {
                                "row": r,
                                "column": column,
                                "column_span": span_value,
                                "vertical_merge": None if merge is None else merge.get(W + "val", "continue"),
                                "text": visible_text(cell),
                            }
                        )
                        column += span_value
                block["cells"] = cells
            record["blocks"].append(block)
        for channel, expression in {
            "deleted": ".//w:del | .//w:moveFrom",
            "hidden": ".//w:r[w:rPr/w:vanish]",
            "comments": ".//w:comment",
            "footnotes": ".//w:footnote",
            "endnotes": ".//w:endnote",
            "text_boxes": ".//w:txbxContent",
            "content_controls": ".//w:sdt",
        }.items():
            for element in root.xpath(expression, namespaces=NS):
                record["channels"].append(
                    {"channel": channel, "part": name, "xml": etree.tostring(element, encoding="unicode")}
                )
        # The original remains byte-for-byte intact. Freeze cached field display in the derivative.
        for element in [*root.iter(W + "del"), *root.iter(W + "moveFrom")]:
            element.getparent().remove(element)
        for tag in ("instrText", "fldChar"):
            for element in list(root.iter(W + tag)):
                element.getparent().remove(element)
        for element in list(root.iter(W + "fldSimple")):
            parent = element.getparent()
            position = parent.index(element)
            for child in list(element):
                parent.insert(position, child)
                position += 1
            parent.remove(element)
        for element in root.iter(W + "updateFields"):
            element.set(W + "val", "false")
        content[name] = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, payload in content.items():
            archive.writestr(name, payload)
    return record, output.getvalue()


def render_word(derivative: bytes, settings: Settings) -> tuple[bytes, dict[str, Any]]:
    executable = shutil.which(settings.extraction_word_renderer)
    if not executable:
        raise ValueError("WORD_RENDERER_UNAVAILABLE")
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    with tempfile.TemporaryDirectory(prefix="extraction-word-") as directory:
        root = Path(directory)
        profile = root / "profile"
        (profile / "user").mkdir(parents=True)
        (profile / "user" / "registrymodifications.xcu").write_text(
            '<?xml version="1.0"?><oor:items xmlns:oor="http://openoffice.org/2001/registry">'
            '<item oor:path="/org.openoffice.Office.Common/Security/Scripting">'
            '<prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>3</value></prop></item>'
            '<item oor:path="/org.openoffice.Office.Writer/Content/Update">'
            '<prop oor:name="Link" oor:op="fuse"><value>2</value></prop></item></oor:items>',
            encoding="utf-8",
        )
        source = root / "source.docx"
        source.write_bytes(derivative)
        environment = {
            key: value
            for key, value in os.environ.items()
            if key.upper()
            in {
                "PATH",
                "SYSTEMROOT",
                "WINDIR",
                "TEMP",
                "TMP",
                "HOME",
                "USERPROFILE",
                "APPDATA",
                "LOCALAPPDATA",
                "FONTCONFIG_PATH",
            }
        }
        environment.update({"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"})
        version = (
            subprocess.run(  # noqa: S603 -- configured executable, fixed arguments, no shell
                [executable, "--version"],
                capture_output=True,
                timeout=15,  # noqa: S603
                check=True,
                creationflags=flags,
            )
            .stdout.decode(errors="replace")
            .strip()
        )  # noqa: S603
        subprocess.run(  # noqa: S603 -- configured renderer, private source directory, no shell
            [
                executable,
                f"-env:UserInstallation={profile.as_uri()}",
                "--headless",
                "--nologo",  # noqa: S603
                "--nodefault",
                "--norestore",
                "--convert-to",
                "pdf:writer_pdf_Export",
                "--outdir",
                str(root),
                str(source),
            ],
            capture_output=True,
            check=True,
            timeout=settings.extraction_word_timeout_seconds,
            creationflags=flags,
            env=environment,
        )
        pdf = root / "source.pdf"
        if not pdf.exists() or pdf.stat().st_size > settings.upload_max_bytes:
            raise ValueError("WORD_RENDER_FAILED")
        font_list = "NOT_AVAILABLE"
        if fonts := shutil.which("fc-list"):
            font_list = subprocess.run(  # noqa: S603 -- fixed font inventory command
                [fonts],
                capture_output=True,
                check=True,
                timeout=15,  # noqa: S603
                creationflags=flags,
            ).stdout.decode(errors="replace")  # noqa: S603
        return pdf.read_bytes(), {
            "version": version,
            "locale": "C.UTF-8",
            "fonts": font_list,
            "field_policy": "freeze_cached_values",
            "revision_view": "current",
            "derivative_sha256": hashlib.sha256(derivative).hexdigest(),
        }
