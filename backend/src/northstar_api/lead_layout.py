from __future__ import annotations

import csv
import io
import re
import zipfile
from datetime import datetime
from typing import Any, Literal
from xml.etree import ElementTree as ET

from pydantic import Field, model_validator

from northstar_api.schemas import APIModel
from northstar_api.services.education_student_import_file import (
    StudentImportFileError,
    _delimited_table,
    _xlsx_table,
)

CORE_SOURCES = {"name", "email", "phone", "status", "consent", "createdAt", "updatedAt", "agentName"}
KEY = "leadLayout"


class LeadColumn(APIModel):
    id: str = Field(pattern=r"^[a-zA-Z][a-zA-Z0-9_]{0,63}$")
    label: str = Field(min_length=1, max_length=100)
    source: str = Field(min_length=1, max_length=100)
    type: Literal["text", "number", "date", "boolean"] = "text"
    format: Literal["plain", "upper", "lower", "yyyy-mm-dd", "dd/mm/yyyy", "mm/dd/yyyy"] = "plain"
    visible: bool = True
    required: bool = False
    crm_targets: dict[str, str] = Field(default_factory=dict, max_length=30)

    @model_validator(mode="after")
    def check_source(self):
        self.label = self.label.strip()
        if not self.label:
            raise ValueError("Column names cannot be blank")
        if self.source not in CORE_SOURCES and not re.fullmatch(
            r"fields\.[a-zA-Z][a-zA-Z0-9_]{0,63}", self.source
        ):
            raise ValueError("Choose a standard field or a custom field key")
        if self.source.split(".")[-1] in {"__proto__", "constructor", "prototype"}:
            raise ValueError("Reserved field key")
        if any(len(target) > 160 for target in self.crm_targets.values()):
            raise ValueError("CRM field names must be at most 160 characters")
        return self


class LeadLayout(APIModel):
    name: str = Field(default="My lead layout", min_length=1, max_length=100)
    version: int = Field(default=0, ge=0)
    columns: list[LeadColumn] = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def unique_columns(self):
        for values in ([c.id for c in self.columns], [c.label.casefold() for c in self.columns]):
            if len(set(values)) != len(values):
                raise ValueError("Column IDs and names must be unique")
        if not any(c.visible for c in self.columns):
            raise ValueError("Keep at least one column visible")
        return self


def default_layout() -> LeadLayout:
    return LeadLayout(
        columns=[
            LeadColumn(id=source, label=label, source=source, type=kind)
            for source, label, kind in [
                ("name", "Lead", "text"),
                ("email", "Email", "text"),
                ("phone", "Phone", "text"),
                ("agentName", "Agent", "text"),
                ("status", "Status", "text"),
                ("consent", "Consent", "boolean"),
                ("createdAt", "Captured", "date"),
            ]
        ]
    )


def stored_layout(workspace) -> LeadLayout:
    data = (workspace.settings_json or {}).get(KEY)
    return LeadLayout.model_validate(data) if data else default_layout()


def parse_template(filename: str, content: bytes) -> LeadLayout:
    if not content or len(content) > 2_000_000:
        raise ValueError("Upload a nonempty CSV or Excel (.xlsx) file up to 2 MB")
    try:
        if filename.lower().endswith(".xlsx"):
            table = _xlsx_table(content, header_only=True)
        elif filename.lower().endswith(".csv"):
            table = _delimited_table(content, ".csv")
        else:
            raise ValueError("Use CSV or Excel .xlsx; save older .xls files as .xlsx first")
    except StudentImportFileError as exc:
        raise ValueError(str(exc)) from exc
    if not table or not 1 <= len(table[0]) <= 64:
        raise ValueError("The first row must contain between 1 and 64 column headers")
    aliases = {
        "lead": "name",
        "full_name": "name",
        "contact_name": "name",
        "email_address": "email",
        "mobile": "phone",
        "whatsapp": "phone",
        "phone_number": "phone",
        "agent": "agentName",
        "captured": "createdAt",
        "created": "createdAt",
        "created_at": "createdAt",
    }
    columns = []
    for index, label in enumerate(table[0]):
        key = re.sub(r"[^a-z0-9]+", "_", label.strip().lower()).strip("_")[:60]
        source = aliases.get(key, key)
        if source not in CORE_SOURCES:
            source = "fields." + (key if key and key[0].isalpha() else f"column_{index + 1}")
        columns.append(
            LeadColumn(
                id=f"column_{index + 1}",
                label=label,
                source=source,
                type="boolean"
                if source == "consent"
                else "date"
                if source in {"createdAt", "updatedAt"}
                else "text",
            )
        )
    return LeadLayout(name="Imported template", columns=columns)


def column_value(lead, column: LeadColumn, agent_name: str = "") -> Any:
    if column.source.startswith("fields."):
        value = (lead.fields_json or {}).get(column.source[7:])
    else:
        attributes = {"agentName": agent_name, "createdAt": lead.created_at, "updatedAt": lead.updated_at}
        value = (
            attributes.get(column.source)
            if column.source in attributes
            else getattr(lead, column.source, None)
        )
    if value is None:
        return ""
    if isinstance(value, datetime):
        value = value.isoformat()
    if column.format in {"upper", "lower"}:
        value = getattr(str(value), column.format)()
    elif column.format in {"yyyy-mm-dd", "dd/mm/yyyy", "mm/dd/yyyy"}:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            value = parsed.strftime(
                {"yyyy-mm-dd": "%Y-%m-%d", "dd/mm/yyyy": "%d/%m/%Y", "mm/dd/yyyy": "%m/%d/%Y"}[column.format]
            )
        except ValueError:
            pass
    if isinstance(value, bool):
        return "Yes" if value else "No"
    return value


def csv_bytes(rows: list[list[Any]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    for row in rows:
        safe = []
        for value in row:
            text = str(value) if value is not None else ""
            if re.match(r"^[\s]*[=+@-]", text) or text.startswith(("\t", "\r", "\n")):
                text = "'" + text
            safe.append(text)
        writer.writerow(safe)
    return stream.getvalue().encode("utf-8-sig")


def xlsx_bytes(rows: list[list[Any]]) -> bytes:
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    root = ET.Element("worksheet", xmlns=ns)
    sheet = ET.SubElement(root, "sheetData")
    for row_index, values in enumerate(rows, 1):
        row = ET.SubElement(sheet, "row", r=str(row_index))
        for index, value in enumerate(values, 1):
            letters = ""
            while index:
                index, rem = divmod(index - 1, 26)
                letters = chr(65 + rem) + letters
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                cell = ET.SubElement(row, "c", r=f"{letters}{row_index}", t="n")
                ET.SubElement(cell, "v").text = str(value)
                continue
            cell = ET.SubElement(row, "c", r=f"{letters}{row_index}", t="inlineStr")
            text = ET.SubElement(
                ET.SubElement(cell, "is"), "t", {"{http://www.w3.org/XML/1998/namespace}space": "preserve"}
            )
            text.text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", str(value) if value is not None else "")[
                :32767
            ]
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>',
        )
        archive.writestr(
            "_rels/.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        )
        archive.writestr(
            "xl/workbook.xml",
            f'<workbook xmlns="{ns}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Leads" sheetId="1" r:id="rId1"/></sheets></workbook>',
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>',
        )
        archive.writestr(
            "xl/worksheets/sheet1.xml", ET.tostring(root, encoding="utf-8", xml_declaration=True)
        )
    return output.getvalue()
