"""Backend-owned workflow presets that can be persisted onto an Agent."""

from __future__ import annotations

from northstar_api.bot_workflow_schemas import BotWorkflowSave, BotWorkflowStep

ENROLLED_STUDENT_TUTOR = "enrolled_student_tutor"


def _step(**values) -> BotWorkflowStep:
    defaults = {
        "buttons": [], "table": None, "template": None, "config": {}, "condition": None,
        "true_step_id": None, "false_step_id": None, "next_step_id": None,
        "position_x": 40, "position_y": 40, "bot_behavior": "complete",
        "waiting_message": "Please choose an option or send the next command.",
        "wait_repeat_count": 0, "repeat_policy": "every_match", "max_sends": None,
        "cooldown_minutes": 0, "calendar_timezone": "Asia/Kolkata", "enabled": True,
    }
    defaults.update(values)
    return BotWorkflowStep(**defaults)


def enrolled_student_tutor() -> BotWorkflowSave:
    """Return the canonical enrollment-aware Education journey."""
    return BotWorkflowSave(
        name="Enrolled student learning journey",
        purpose="education",
        status="draft",
        steps=[
            _step(
                id="edu_daily_welcome",
                name="Daily welcome (first message)",
                trigger_type="fallback",
                trigger_value="",
                message_format="text",
                message=(
                    "👋 *Welcome back to your learning assistant!*\n\n"
                    "I’ll continue with your active course. Send *courses* at any time to view or "
                    "switch your enrolled course."
                ),
                config={"systemAction": "education_daily_welcome", "continueOriginalMessage": True},
                repeat_policy="once_per_calendar_day",
                position_x=36,
                position_y=54,
            ),
            _step(
                id="edu_enrollment_route",
                name="Route by active enrollments",
                trigger_type="command",
                trigger_value="courses",
                message_format="list",
                message="Choose the course you want to study.",
                config={
                    "systemAction": "education_course_menu",
                    "dynamicSource": "verified_active_enrollments",
                    "header": "Your courses",
                    "footer": "Only courses you are currently enrolled in are shown.",
                    "action": {"button": "Choose course", "sections": [{"title": "Active enrollments", "rows": []}]},
                },
                next_step_id="edu_course_session",
                position_x=330,
                position_y=54,
                bot_behavior="wait_for_next_trigger",
                waiting_message="Reply with the course number or course name.",
                wait_repeat_count=2,
            ),
            _step(
                id="edu_course_session",
                name="Continue selected course",
                trigger_type="contains",
                trigger_value="study",
                message_format="text",
                message=(
                    "✅ Your course is selected. Ask any question from this course and I’ll answer "
                    "using its trained material."
                ),
                config={"systemAction": "education_continue_active_course", "persistUntil": "switch_course"},
                position_x=624,
                position_y=54,
            ),
            _step(
                id="edu_switch_course",
                name="Switch course",
                trigger_type="command",
                trigger_value="switch course",
                message_format="list",
                message="Choose another enrolled course.",
                config={
                    "systemAction": "education_course_menu",
                    "dynamicSource": "verified_active_enrollments",
                    "header": "Switch course",
                    "footer": "Your new choice remains active until you switch again.",
                    "action": {"button": "Switch course", "sections": [{"title": "Active enrollments", "rows": []}]},
                },
                next_step_id="edu_course_session",
                position_x=330,
                position_y=220,
                bot_behavior="wait_for_next_trigger",
                waiting_message="Reply with the course number or course name.",
                wait_repeat_count=2,
            ),
            _step(
                id="edu_help",
                name="How to use the tutor",
                trigger_type="command",
                trigger_value="help",
                message_format="buttons",
                message=(
                    "Ask any course question normally. If you are enrolled in more than one course, "
                    "send *courses* or *switch course* whenever you want to change subjects."
                ),
                buttons=[
                    {"id": "courses", "title": "My courses"},
                    {"id": "switch_course", "title": "Switch course"},
                ],
                position_x=624,
                position_y=220,
            ),
        ],
    )


def template(template_key: str) -> BotWorkflowSave | None:
    if template_key == ENROLLED_STUDENT_TUTOR:
        return enrolled_student_tutor()
    return None


def template_catalog() -> list[dict[str, object]]:
    workflow = enrolled_student_tutor()
    return [{
        "key": ENROLLED_STUDENT_TUTOR,
        "name": "Enrolled Student Tutor",
        "purpose": "education",
        "description": (
            "Daily welcome, enrollment-aware course routing, remembered study context and secure course switching."
        ),
        "workflow": workflow.model_dump(mode="json", by_alias=True),
    }]
