from __future__ import annotations

import csv
import io
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from northstar_api.database import SessionFactory
from northstar_api.lead_crm.mapping import build_mapped_payload
from northstar_api.lead_crm.models import LeadProfile
from northstar_api.lead_layout import LeadLayout, csv_bytes, parse_template, xlsx_bytes
from northstar_api.models import Agent, Lead, Workspace
from northstar_api.services.education_student_import_file import _xlsx_table


def test_templates_preserve_order_and_do_not_interpret_formulas():
    content = b"Customer,Email,Phone,Course,Amount\r\nSample,sample@example.com,+91000,ABC,12\r\n"
    layout = parse_template("sample.csv", content)
    assert [c.label for c in layout.columns] == ["Customer", "Email", "Phone", "Course", "Amount"]
    assert layout.columns[1].source == "email"
    workbook = xlsx_bytes([["Phone", "Budget", "Notes"], ["+919876543210", 10.5, '=HYPERLINK("bad")']])
    assert _xlsx_table(workbook)[1] == ["+919876543210", "10.5", '=HYPERLINK("bad")']
    assert [c.label for c in parse_template("format.xlsx", workbook).columns] == ["Phone", "Budget", "Notes"]
    assert "'=SUM" in csv_bytes([["=SUM(1,2)"]]).decode("utf-8-sig")
    large_workbook = xlsx_bytes([["Name", "Email"], *[["Sample", "example@example.com"] for _ in range(600)]])
    assert len(parse_template("large.xlsx", large_workbook).columns) == 2
    with pytest.raises((ValueError, ValidationError)):
        parse_template("bad.csv", b"Email,Email\n")
    with pytest.raises(ValueError):
        parse_template("old.xls", b"not an xlsx file")


@pytest.mark.usefixtures("crm_test_plan")
async def test_saved_layout_edit_and_complete_export(client, auth_headers):
    headers = auth_headers
    current = await client.get("/api/v1/leads/layout", headers=headers)
    assert current.status_code == 200, current.text
    initial = current.json()
    imported = await client.post(
        "/api/v1/leads/layout/template",
        headers=headers,
        files={"file": ("format.csv", b"Email,Course,Budget\nnot-an-email,Sample,1\n", "text/csv")},
    )
    assert imported.status_code == 200, imported.text
    draft = imported.json()
    draft["version"] = initial["version"]
    draft["columns"][1]["required"] = True
    draft["columns"][2]["type"] = "number"
    saved = await client.put("/api/v1/leads/layout", headers=headers, json=draft)
    assert saved.status_code == 200, saved.text
    assert (await client.put("/api/v1/leads/layout", headers=headers, json=draft)).status_code == 409
    unique = uuid4().hex[:10]
    agent_response = await client.post("/api/v1/agents", headers=headers, json={"name": "Layout " + unique})
    assert agent_response.status_code == 201, agent_response.text
    async with SessionFactory() as session:
        agent = await session.get(Agent, UUID(agent_response.json()["id"]))
        rows = [
            Lead(
                tenant_id=agent.tenant_id,
                workspace_id=agent.workspace_id,
                agent_id=agent.id,
                name="Layout " + unique,
                email=f"layout-{i}@example.com",
                fields_json={"course": "Math", "budget": i},
            )
            for i in range(55)
        ]
        session.add_all(rows)
        await session.commit()
        lead_id = rows[0].id
        workspace_id = agent.workspace_id
    edited = await client.patch(
        f"/api/v1/leads/{lead_id}/details",
        headers=headers,
        json={"email": "edited@example.com", "fields": {"course": "Science", "budget": "123.5"}},
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["fields"]["budget"] == 123.5
    invalid = await client.patch(
        f"/api/v1/leads/{lead_id}/details", headers=headers, json={"fields": {"budget": "bad"}}
    )
    assert invalid.status_code == 422
    missing = await client.patch(
        f"/api/v1/leads/{lead_id}/details", headers=headers, json={"fields": {"course": ""}}
    )
    assert missing.status_code == 422
    async with SessionFactory() as session:
        lead = await session.get(Lead, lead_id)
        profile = await session.scalar(select(LeadProfile).where(LeadProfile.lead_id == lead_id))
        mapped = build_mapped_payload(
            lead,
            profile,
            {
                "fields": [
                    {"source": "customFields.course", "target": "Course_Name", "transform": "upper"},
                    {"source": "customFields.budget", "target": "Amount"},
                ]
            },
            provider="generic_rest",
        )
        assert mapped == {"Course_Name": "SCIENCE", "Amount": 123.5}
    for format in ("csv", "xlsx"):
        exported = await client.get(
            "/api/v1/leads/layout/export", headers=headers, params={"search": unique, "format": format}
        )
        assert exported.status_code == 200, exported.text[:200] if format == "csv" else exported.status_code
        data = (
            list(csv.reader(io.StringIO(exported.content.decode("utf-8-sig"))))
            if format == "csv"
            else _xlsx_table(exported.content)
        )
        assert data[0] == ["Email", "Course", "Budget"]
        assert len(data) == 56  # All matching leads, including the next UI page.
    other = await client.post(
        "/api/v1/workspaces",
        headers=headers,
        json={"name": "Layout other " + unique, "slug": "layout-other-" + unique},
    )
    assert other.status_code == 201, other.text
    other_headers = {**headers, "X-Workspace-ID": other.json()["id"]}
    assert (await client.get("/api/v1/leads/layout", headers=other_headers)).json()["version"] == 0
    assert (
        await client.patch(
            f"/api/v1/leads/{lead_id}/details", headers=other_headers, json={"name": "Forbidden"}
        )
    ).status_code == 404
    # Restore this session's shared test workspace layout.
    async with SessionFactory() as session:
        workspace = await session.get(Workspace, workspace_id)
        workspace.settings_json = {
            **(workspace.settings_json or {}),
            "leadLayout": LeadLayout.model_validate(initial).model_dump(),
        }
        await session.commit()
