from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from httpx import AsyncClient
from pydantic import ValidationError

from northstar_api.bot_workflow_schemas import BotWorkflowSave, BotWorkflowStep
from northstar_api.services.bot_workflow_templates import enrolled_student_tutor
from northstar_api.services.bot_workflows import _allowed_by_frequency, _matches, _render, _waiting_reply

pytestmark = pytest.mark.usefixtures("crm_test_plan")


def test_workflow_command_and_keyword_matching() -> None:
    assert _matches({"triggerType": "command", "triggerValue": "/courses"}, "/COURSES")
    assert _matches({"triggerType": "contains", "triggerValue": "refund status"}, "What is my refund status?")
    assert not _matches({"triggerType": "command", "triggerValue": "/courses"}, "/courses now")


def test_workflow_renders_buttons_and_tables() -> None:
    buttons = _render({"id": "menu", "messageFormat": "buttons", "message": "Choose", "buttons": [{"id": "cma", "title": "CMA"}]})
    assert buttons.message_format["buttons"][0]["title"] == "CMA"
    table = _render({"id": "status", "messageFormat": "table", "message": "Access", "table": {"columns": ["Course", "Status"], "rows": [["CMA", "Active"]]}})
    assert "Course | Status" in table.content
    assert table.message_format["body"] == "Access"


def test_button_workflow_enforces_whatsapp_limits() -> None:
    with pytest.raises(ValidationError, match="1024"):
        BotWorkflowStep(id="long", name="Long", triggerType="command", triggerValue="/long", messageFormat="buttons", message="x" * 1025, buttons=[{"id": "ok", "title": "OK"}])


def test_calendar_day_and_rolling_24_hour_rules_are_distinct() -> None:
    now = datetime(2026, 9, 20, 0, 15, tzinfo=UTC)
    sent = [SimpleNamespace(created_at=now - timedelta(minutes=30), content_json={"workflowStepId": "welcome"})]
    daily = {"id": "welcome", "repeatPolicy": "once_per_calendar_day", "calendarTimezone": "UTC"}
    rolling = {"id": "welcome", "repeatPolicy": "once_per_24_hours"}
    assert _allowed_by_frequency(daily, sent, now)
    assert not _allowed_by_frequency(rolling, sent, now)


def test_waiting_bot_repeats_only_configured_number_of_times() -> None:
    step = {"id": "menu", "botBehavior": "wait_for_next_trigger", "waitRepeatCount": 1, "waitingMessage": "Choose an option"}
    assert _waiting_reply(step, []).content == "Choose an option"
    sent = [SimpleNamespace(content_json={"workflowWaitingFor": "menu"})]
    assert _waiting_reply(step, sent) is None


def test_active_workflow_rejects_a_connection_to_a_missing_node() -> None:
    with pytest.raises(ValidationError, match="next step"):
        BotWorkflowSave(name="Connected flow", purpose="support", status="active", steps=[
            BotWorkflowStep(id="welcome", name="Welcome", triggerType="command", triggerValue="/start", message="Hi", nextStepId="missing")
        ])


def test_active_location_accepts_zero_coordinates_and_rejects_missing_coordinates() -> None:
    valid = BotWorkflowSave(name="Zero location", purpose="support", status="active", steps=[
        BotWorkflowStep(
            id="origin", name="Origin", triggerType="command", triggerValue="/origin",
            messageFormat="location", config={"latitude": 0, "longitude": 0},
        )
    ])
    assert valid.steps[0].config["latitude"] == 0
    with pytest.raises(ValidationError, match="numeric latitude and longitude"):
        BotWorkflowSave(name="Bad location", purpose="support", status="active", steps=[
            BotWorkflowStep(
                id="bad", name="Bad", triggerType="command", triggerValue="/bad",
                messageFormat="location", config={"latitude": 10},
            )
        ])


def test_active_workflow_rejects_invalid_false_branch_and_cycles() -> None:
    with pytest.raises(ValidationError, match="false branch"):
        BotWorkflowSave(name="Bad branch", purpose="support", status="active", steps=[
            BotWorkflowStep(
                id="route", name="Route", triggerType="condition",
                condition={"field": "channel", "operator": "equals", "value": "web"},
                trueStepId="answer", falseStepId="missing",
            ),
            BotWorkflowStep(id="answer", name="Answer", triggerType="fallback", message="Hello"),
        ])
    with pytest.raises(ValidationError, match="must not contain cycles"):
        BotWorkflowSave(name="Cycle", purpose="support", status="active", steps=[
            BotWorkflowStep(
                id="one", name="One", triggerType="command", triggerValue="/one",
                message="One", nextStepId="two",
            ),
            BotWorkflowStep(
                id="two", name="Two", triggerType="contains", triggerValue="two",
                message="Two", nextStepId="one",
            ),
        ])


def test_active_rich_message_requires_delivery_payload() -> None:
    with pytest.raises(ValidationError, match="mediaId or HTTPS URL"):
        BotWorkflowSave(name="Bad media", purpose="support", status="active", steps=[
            BotWorkflowStep(
                id="image", name="Image", triggerType="command", triggerValue="/image",
                messageFormat="image", message="Image", config={},
            )
        ])


def test_enrolled_student_template_is_backend_owned_and_calendar_scoped() -> None:
    workflow = enrolled_student_tutor()
    assert workflow.purpose.value == "education"
    assert workflow.status == "draft"
    assert [step.id for step in workflow.steps] == [
        "edu_daily_welcome", "edu_enrollment_route", "edu_course_session",
        "edu_switch_course", "edu_help",
    ]
    welcome = workflow.steps[0]
    assert welcome.repeat_policy == "once_per_calendar_day"
    assert welcome.calendar_timezone == "Asia/Kolkata"
    assert welcome.config == {
        "systemAction": "education_daily_welcome", "continueOriginalMessage": True
    }
    assert workflow.steps[1].config["dynamicSource"] == "verified_active_enrollments"
    assert workflow.steps[3].trigger_value == "switch course"


async def test_template_catalog_applies_and_persists_for_an_education_agent(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    workspace = await client.get("/api/v1/workspace", headers=auth_headers)
    headers = {**auth_headers, "X-Workspace-ID": workspace.json()["id"]}
    created = await client.post("/api/v1/agents", headers=headers, json={
        "name": "Template Education Bot",
        "description": "Template integration test",
        "purpose": "education",
        "deploymentChannel": "whatsapp",
    })
    assert created.status_code == 201, created.text
    catalog = await client.get("/api/v1/bot-workflows/templates", headers=headers)
    assert catalog.status_code == 200, catalog.text
    assert catalog.json()[0]["key"] == "enrolled_student_tutor"
    applied = await client.post(
        f"/api/v1/bot-workflows/{created.json()['id']}/templates/enrolled_student_tutor",
        headers=headers,
    )
    assert applied.status_code == 200, applied.text
    body = applied.json()
    assert body["status"] == "draft"
    assert body["steps"][0]["config"]["systemAction"] == "education_daily_welcome"
    saved = await client.get(f"/api/v1/bot-workflows/{created.json()['id']}", headers=headers)
    assert saved.status_code == 200
    assert saved.json()["id"] == body["id"]
