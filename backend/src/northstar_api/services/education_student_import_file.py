from __future__ import annotations

import csv
import io
import json
import posixpath
import re
import zipfile
from datetime import date, timedelta
from pathlib import PurePosixPath
from xml.etree import ElementTree

from pydantic import ValidationError

from northstar_api.education_student_import_schemas import StudentImportRow

_MAX_FILE_BYTES = 2_000_000
_MAX_UNCOMPRESSED_XLSX_BYTES = 20_000_000
_MAX_ROWS = 500
_MAX_COLUMNS = 64
_MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_DATE_FORMAT_IDS = {14, 15, 16, 17, 18, 19, 20, 21, 22, 27, 30, 36, 45, 46, 47, 50, 57}
_CELL_REFERENCE = re.compile(r"^([A-Z]+)\d+$")
_DATE_FORMAT_TOKEN = re.compile(r"[ymdhis]", re.IGNORECASE)

_HEADER_ALIASES: dict[str, str] = {
    "student_id": "student_number",
    "student_number": "student_number",
    "studentnumber": "student_number",
    "student": "student_number",
    "name": "name",
    "student_name": "name",
    "email": "email",
    "identity_type": "identity_type",
    "identitytype": "identity_type",
    "identifier": "identifier",
    "identity": "identifier",
    "phone": "identifier",
    "identity_verified": "identity_verified",
    "identityverified": "identity_verified",
    "course": "course_code",
    "course_code": "course_code",
    "coursecode": "course_code",
    "batch": "batch_code",
    "batch_code": "batch_code",
    "batchcode": "batch_code",
    "agent": "agent_public_id",
    "agent_id": "agent_public_id",
    "agent_public_id": "agent_public_id",
    "agentpublicid": "agent_public_id",
    "enrollment_status": "enrollment_status",
    "enrollmentstatus": "enrollment_status",
    "starts_on": "starts_on",
    "start_date": "starts_on",
    "startson": "starts_on",
    "ends_on": "ends_on",
    "end_date": "ends_on",
    "endson": "ends_on",
    "custom_fields": "custom_fields",
    "custom_fields_json": "custom_fields",
    "customfields": "custom_fields",
}


class StudentImportFileError(ValueError):
    pass


def parse_student_import_file(filename: str, content: bytes) -> list[StudentImportRow]:
    if not content:
        raise StudentImportFileError("Import file is empty")
    if len(content) > _MAX_FILE_BYTES:
        raise StudentImportFileError("Import file must be 2 MB or smaller")
    suffix = PurePosixPath(filename.lower()).suffix
    if suffix == ".xlsx":
        table = _xlsx_table(content)
    elif suffix in {".csv", ".tsv", ".txt"}:
        table = _delimited_table(content, suffix)
    else:
        raise StudentImportFileError("Use a .csv, .tsv, .txt, or .xlsx import file")
    return _rows_from_table(table)


def _delimited_table(content: bytes, suffix: str) -> list[list[str]]:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise StudentImportFileError("CSV/TSV files must use UTF-8 text encoding") from exc
    lines = text.splitlines()
    first_line = lines[0] if lines else ""
    delimiter = "\t" if suffix == ".tsv" or ("\t" in first_line and "," not in first_line) else ","
    try:
        table = [list(row) for row in csv.reader(io.StringIO(text), delimiter=delimiter)]
    except csv.Error as exc:
        raise StudentImportFileError(f"CSV/TSV could not be parsed: {exc}") from exc
    return [row for row in table if any(value.strip() for value in row)]


def _xlsx_table(content: bytes, *, header_only: bool = False) -> list[list[str]]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as exc:
        raise StudentImportFileError("The .xlsx file is not a valid Excel workbook") from exc
    with archive:
        total_uncompressed = sum(info.file_size for info in archive.infolist())
        if total_uncompressed > _MAX_UNCOMPRESSED_XLSX_BYTES:
            raise StudentImportFileError("Excel workbook expands beyond the 20 MB safety limit")
        required = {"xl/workbook.xml", "xl/_rels/workbook.xml.rels"}
        if not required.issubset(archive.namelist()):
            raise StudentImportFileError("Excel workbook is missing its worksheet metadata")
        workbook = _xml(archive.read("xl/workbook.xml"), "Excel workbook metadata")
        relations = _xml(archive.read("xl/_rels/workbook.xml.rels"), "Excel workbook relationships")
        sheet_path = _first_sheet_path(workbook, relations)
        if sheet_path not in archive.namelist():
            raise StudentImportFileError("Excel workbook first worksheet could not be found")
        shared_strings = _shared_strings(archive)
        date_styles = _date_style_indexes(archive)
        uses_1904_dates = _uses_1904_date_system(workbook)
        sheet = _xml(archive.read(sheet_path), "Excel worksheet")
        return _sheet_table(sheet, shared_strings, date_styles, uses_1904_dates, header_only=header_only)


def _xml(content: bytes, label: str) -> ElementTree.Element:
    try:
        # XLSX members are size-capped above and ElementTree does not resolve external entities here.
        return ElementTree.fromstring(content)  # noqa: S314
    except ElementTree.ParseError as exc:
        raise StudentImportFileError(f"{label} is malformed") from exc


def _first_sheet_path(workbook: ElementTree.Element, relations: ElementTree.Element) -> str:
    sheet = workbook.find(f"{{{_MAIN_NS}}}sheets/{{{_MAIN_NS}}}sheet")
    if sheet is None:
        raise StudentImportFileError("Excel workbook does not contain a worksheet")
    relation_id = sheet.attrib.get(f"{{{_REL_NS}}}id")
    if not relation_id:
        raise StudentImportFileError("Excel worksheet relationship is missing")
    target = None
    for relation in relations.findall(f"{{{_PACKAGE_REL_NS}}}Relationship"):
        if relation.attrib.get("Id") == relation_id:
            target = relation.attrib.get("Target")
            break
    if not target:
        raise StudentImportFileError("Excel worksheet relationship could not be resolved")
    normalized = (
        posixpath.normpath(target.lstrip("/"))
        if target.startswith("/")
        else posixpath.normpath(posixpath.join("xl", target))
    )
    if normalized.startswith("../") or normalized == "..":
        raise StudentImportFileError("Excel worksheet path is invalid")
    return normalized


def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = _xml(archive.read("xl/sharedStrings.xml"), "Excel shared strings")
    values: list[str] = []
    for item in root.findall(f"{{{_MAIN_NS}}}si"):
        values.append("".join(node.text or "" for node in item.iter(f"{{{_MAIN_NS}}}t")))
    return values


def _date_style_indexes(archive: zipfile.ZipFile) -> set[int]:
    if "xl/styles.xml" not in archive.namelist():
        return set()
    root = _xml(archive.read("xl/styles.xml"), "Excel styles")
    custom_formats: dict[int, str] = {}
    for item in root.findall(f"{{{_MAIN_NS}}}numFmts/{{{_MAIN_NS}}}numFmt"):
        try:
            format_id = int(item.attrib.get("numFmtId", ""))
        except ValueError:
            continue
        custom_formats[format_id] = item.attrib.get("formatCode", "")
    date_styles: set[int] = set()
    cell_formats = root.find(f"{{{_MAIN_NS}}}cellXfs")
    if cell_formats is None:
        return date_styles
    for index, item in enumerate(cell_formats.findall(f"{{{_MAIN_NS}}}xf")):
        try:
            format_id = int(item.attrib.get("numFmtId", "0"))
        except ValueError:
            continue
        custom = custom_formats.get(format_id, "")
        cleaned = re.sub(r'"[^"]*"|\\.', "", custom)
        if format_id in _DATE_FORMAT_IDS or (custom and _DATE_FORMAT_TOKEN.search(cleaned)):
            date_styles.add(index)
    return date_styles


def _uses_1904_date_system(workbook: ElementTree.Element) -> bool:
    properties = workbook.find(f"{{{_MAIN_NS}}}workbookPr")
    if properties is None:
        return False
    return properties.attrib.get("date1904", "0").lower() in {"1", "true"}


def _column_index(reference: str) -> int:
    match = _CELL_REFERENCE.match(reference.upper())
    if match is None:
        raise StudentImportFileError(f"Excel cell reference {reference!r} is invalid")
    value = 0
    for character in match.group(1):
        value = value * 26 + ord(character) - ord("A") + 1
    return value - 1


def _sheet_table(
    sheet: ElementTree.Element,
    shared_strings: list[str],
    date_styles: set[int],
    uses_1904_dates: bool,
    *,
    header_only: bool = False,
) -> list[list[str]]:
    table: list[list[str]] = []
    for row_node in sheet.findall(f".//{{{_MAIN_NS}}}sheetData/{{{_MAIN_NS}}}row"):
        cells: dict[int, str] = {}
        for cell in row_node.findall(f"{{{_MAIN_NS}}}c"):
            reference = cell.attrib.get("r")
            if not reference:
                continue
            column = _column_index(reference)
            if column >= _MAX_COLUMNS:
                raise StudentImportFileError(f"Excel import supports at most {_MAX_COLUMNS} columns")
            cells[column] = _cell_value(cell, shared_strings, date_styles, uses_1904_dates)
        if not cells:
            continue
        width = max(cells) + 1
        row = [cells.get(index, "") for index in range(width)]
        if any(value.strip() for value in row):
            table.append(row)
            if header_only:
                break
            if len(table) > _MAX_ROWS + 1:
                raise StudentImportFileError(f"Import supports at most {_MAX_ROWS} student rows")
    return table


def _cell_value(
    cell: ElementTree.Element,
    shared_strings: list[str],
    date_styles: set[int],
    uses_1904_dates: bool,
) -> str:
    cell_type = cell.attrib.get("t", "n")
    if cell_type == "inlineStr":
        return "".join(node.text or "" for node in cell.iter(f"{{{_MAIN_NS}}}t"))
    value_node = cell.find(f"{{{_MAIN_NS}}}v")
    value = value_node.text if value_node is not None and value_node.text is not None else ""
    if cell_type == "s":
        try:
            return shared_strings[int(value)]
        except (ValueError, IndexError) as exc:
            raise StudentImportFileError("Excel shared-string reference is invalid") from exc
    if cell_type == "b":
        return "true" if value == "1" else "false"
    if cell_type in {"str", "d", "e"}:
        return value
    try:
        style_index = int(cell.attrib.get("s", "0"))
    except ValueError:
        style_index = 0
    if style_index in date_styles and value:
        try:
            serial = float(value)
        except ValueError:
            return value
        base = date(1904, 1, 1) if uses_1904_dates else date(1899, 12, 30)
        return (base + timedelta(days=int(serial))).isoformat()
    return value


def _normalized_header(value: str) -> str:
    return re.sub(r"[\s-]+", "_", value.strip().lower())


def _rows_from_table(table: list[list[str]]) -> list[StudentImportRow]:
    if len(table) < 2:
        raise StudentImportFileError("Import file must contain a header row and at least one student row")
    if len(table) - 1 > _MAX_ROWS:
        raise StudentImportFileError(f"Import supports at most {_MAX_ROWS} student rows")
    headers = table[0]
    mapped: list[str | None] = []
    unknown: list[str] = []
    for header in headers:
        normalized = _normalized_header(header)
        target = _HEADER_ALIASES.get(normalized) if normalized else None
        mapped.append(target)
        if normalized and target is None:
            unknown.append(header.strip())
    if unknown:
        raise StudentImportFileError(f"Unknown import columns: {', '.join(unknown)}")
    if "student_number" not in mapped or "name" not in mapped:
        raise StudentImportFileError("Import requires student_id and name columns")
    mapped_values = [value for value in mapped if value is not None]
    duplicates = sorted({value for value in mapped_values if mapped_values.count(value) > 1})
    if duplicates:
        raise StudentImportFileError(f"Duplicate import columns: {', '.join(duplicates)}")

    rows: list[StudentImportRow] = []
    errors: list[str] = []
    for row_number, values in enumerate(table[1:], start=2):
        raw: dict[str, object] = {}
        for column, field_name in enumerate(mapped):
            if field_name is None:
                continue
            raw_value = values[column].strip() if column < len(values) else ""
            if field_name == "identity_verified":
                raw[field_name] = _parse_boolean(raw_value, row_number)
            elif field_name == "custom_fields":
                raw[field_name] = _parse_custom_fields(raw_value, row_number)
            elif field_name == "enrollment_status":
                raw[field_name] = raw_value or "active"
            else:
                raw[field_name] = raw_value or None
        try:
            rows.append(StudentImportRow.model_validate(raw))
        except ValidationError as exc:
            details = "; ".join(error["msg"] for error in exc.errors())
            errors.append(f"Row {row_number}: {details}")
    if errors:
        raise StudentImportFileError(" | ".join(errors[:20]))
    return rows


def _parse_boolean(value: str, row_number: int) -> bool:
    normalized = value.strip().lower()
    if not normalized:
        return False
    if normalized in {"true", "yes", "y", "1", "verified"}:
        return True
    if normalized in {"false", "no", "n", "0", "pending"}:
        return False
    raise StudentImportFileError(
        f"Row {row_number}: identity_verified must be true/false, yes/no, or 1/0"
    )


def _parse_custom_fields(value: str, row_number: int) -> dict[str, object]:
    if not value.strip():
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise StudentImportFileError(f"Row {row_number}: custom_fields must be valid JSON") from exc
    if not isinstance(parsed, dict):
        raise StudentImportFileError(f"Row {row_number}: custom_fields must be a JSON object")
    return parsed
