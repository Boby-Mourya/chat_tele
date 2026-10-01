from __future__ import annotations

import io
import zipfile

import pytest
from httpx import AsyncClient

from northstar_api.services.education_student_import_file import parse_student_import_file


def _xlsx_fixture() -> bytes:
    workbook = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets><sheet name="Students" sheetId="1" r:id="rId1"/></sheets>
</workbook>"""
    relations = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>"""
    styles = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <cellXfs count="2"><xf numFmtId="0"/><xf numFmtId="14"/></cellXfs>
</styleSheet>"""

    def inline(reference: str, value: str) -> str:
        return f'<c r="{reference}" t="inlineStr"><is><t>{value}</t></is></c>'

    headers = [
        "student_id",
        "name",
        "email",
        "identity_type",
        "identifier",
        "identity_verified",
        "course_code",
        "batch_code",
        "agent_id",
        "enrollment_status",
        "starts_on",
        "ends_on",
        "custom_fields",
    ]
    header_cells = "".join(
        inline(f"{chr(ord('A') + index)}1", value) for index, value in enumerate(headers)
    )
    row_cells = "".join(
        [
            inline("A2", "STUDENT-XLSX-1"),
            inline("B2", "Asha Verma"),
            inline("C2", "Asha@Example.com"),
            inline("D2", "whatsapp"),
            inline("E2", "+919876543210"),
            '<c r="F2" t="b"><v>1</v></c>',
            inline("G2", "CPA"),
            inline("H2", "CPA-2027-A"),
            inline("I2", "agt_education"),
            inline("J2", "active"),
            '<c r="K2" s="1"><v>46388</v></c>',
            '<c r="L2" s="1"><v>46568</v></c>',
            inline("M2", '{"language":"en"}'),
        ]
    )
    sheet = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData><row r="1">{header_cells}</row><row r="2">{row_cells}</row></sheetData>
</worksheet>"""
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", relations)
        archive.writestr("xl/styles.xml", styles)
        archive.writestr("xl/worksheets/sheet1.xml", sheet)
    return output.getvalue()


def test_xlsx_parser_supports_boolean_and_excel_date_cells() -> None:
    rows = parse_student_import_file("students.xlsx", _xlsx_fixture())
    assert len(rows) == 1
    row = rows[0]
    assert row.student_number == "STUDENT-XLSX-1"
    assert row.name == "Asha Verma"
    assert str(row.email) == "asha@example.com"
    assert row.identity_type.value == "whatsapp"
    assert row.identifier == "+919876543210"
    assert row.identity_verified is True
    assert row.course_code == "CPA"
    assert row.batch_code == "CPA-2027-A"
    assert row.starts_on.isoformat() == "2027-01-01"
    assert row.ends_on.isoformat() == "2027-06-30"
    assert row.custom_fields == {"language": "en"}


@pytest.mark.anyio
async def test_xlsx_upload_endpoint_returns_normalized_import_rows(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    workspace = await client.get("/api/v1/workspace", headers=auth_headers)
    assert workspace.status_code == 200, workspace.text
    headers = {**auth_headers, "X-Workspace-ID": workspace.json()["id"]}
    response = await client.post(
        "/api/v1/education/students/import/parse-file",
        headers=headers,
        files={
            "file": (
                "students.xlsx",
                _xlsx_fixture(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["rows"]) == 1
    assert body["rows"][0]["studentNumber"] == "STUDENT-XLSX-1"
    assert body["rows"][0]["email"] == "asha@example.com"
    assert body["rows"][0]["identityVerified"] is True
    assert body["rows"][0]["startsOn"] == "2027-01-01"
    assert body["rows"][0]["endsOn"] == "2027-06-30"
