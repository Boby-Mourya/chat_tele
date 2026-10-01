from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.models import BotWorkflow, Message, MessageRole


@dataclass(frozen=True, slots=True)
class WorkflowReply:
    content: str
    message_format: dict[str, Any]


def _matches(step: dict[str, Any], incoming: str) -> bool:
    trigger = str(step.get("triggerValue") or step.get("trigger_value") or "").strip().casefold()
    kind = step.get("triggerType") or step.get("trigger_type")
    normalized = incoming.strip().casefold()
    if kind == "fallback":
        return True
    if kind == "command":
        return normalized == trigger or normalized == trigger.lstrip("/")
    return bool(trigger and trigger in normalized)


def _render(step: dict[str, Any]) -> WorkflowReply:
    kind = str(step.get("messageFormat") or step.get("message_format") or "text")
    body = str(step.get("message") or "").strip()
    payload: dict[str, Any] = {
        "type": kind,
        "workflowStepId": step.get("id"),
        "workflowBotBehavior": step.get("botBehavior") or step.get("bot_behavior") or "complete",
    }
    payload["config"] = step.get("config") or {}
    if kind == "buttons":
        buttons = list(step.get("buttons") or [])
        payload["buttons"] = buttons
        return WorkflowReply(body, payload)
    if kind == "table":
        table = step.get("table") or {}
        columns = list(table.get("columns") or [])
        rows = list(table.get("rows") or [])
        payload.update({"body": body, "table": {"columns": columns, "rows": rows}})
        lines = [" | ".join(columns), " | ".join("---" for _ in columns)]
        lines.extend(" | ".join(str(cell) for cell in row) for row in rows)
        return WorkflowReply(f"{body}\n\n" + "\n".join(lines), payload)
    if kind == "template":
        payload["template"] = step.get("template")
        payload["type"] = "template"
        return WorkflowReply(body, payload)
    payload["type"] = kind
    return WorkflowReply(body or f"[{kind.replace('_', ' ')}]", payload)


def _allowed_by_frequency(step: dict[str, Any], sent: list[Message], now: datetime) -> bool:
    step_id = str(step.get("id"))
    previous = [item for item in sent if str((item.content_json or {}).get("workflowStepId")) == step_id]
    max_sends = step.get("maxSends") if "maxSends" in step else step.get("max_sends")
    if max_sends is not None and len(previous) >= int(max_sends):
        return False
    if not previous:
        return True
    latest = max(item.created_at for item in previous)
    if latest.tzinfo is None:
        latest = latest.replace(tzinfo=UTC)
    cooldown = int(step.get("cooldownMinutes") or step.get("cooldown_minutes") or 0)
    if cooldown and now - latest < timedelta(minutes=cooldown):
        return False
    policy = step.get("repeatPolicy") or step.get("repeat_policy") or "every_match"
    if policy == "once_per_conversation":
        return False
    if policy == "once_per_24_hours":
        return now - latest >= timedelta(hours=24)
    if policy == "once_per_calendar_day":
        zone = ZoneInfo(str(step.get("calendarTimezone") or step.get("calendar_timezone") or "Asia/Kolkata"))
        return latest.astimezone(zone).date() < now.astimezone(zone).date()
    return True


def _waiting_reply(step: dict[str, Any], sent: list[Message]) -> WorkflowReply | None:
    if (step.get("botBehavior") or step.get("bot_behavior")) != "wait_for_next_trigger":
        return None
    step_id = str(step.get("id"))
    reminders = [item for item in sent if (item.content_json or {}).get("workflowWaitingFor") == step_id]
    limit = int(step.get("waitRepeatCount") or step.get("wait_repeat_count") or 0)
    if len(reminders) >= limit:
        return None
    content = str(step.get("waitingMessage") or step.get("waiting_message") or "Please send the next command.")
    return WorkflowReply(content, {"type": "text", "workflowStepId": step_id, "workflowWaitingFor": step_id, "workflowBotBehavior": "wait_for_next_trigger"})


async def match_bot_workflow(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    agent_id: UUID,
    conversation_id: UUID,
    message: str,
    channel: str = "widget",
    include_fallback: bool = True,
) -> WorkflowReply | None:
    workflow = await session.scalar(
        select(BotWorkflow).where(
            BotWorkflow.tenant_id == tenant_id,
            BotWorkflow.workspace_id == workspace_id,
            BotWorkflow.agent_id == agent_id,
            BotWorkflow.status == "active",
        )
    )
    if not workflow:
        return None
    sent = list((await session.scalars(
        select(Message).where(
            Message.conversation_id == conversation_id,
            Message.role == MessageRole.ASSISTANT,
            Message.finish_reason == "stop",
        ).order_by(Message.created_at.desc())
    )).all())
    now = datetime.now(UTC)
    enabled = [step for step in (workflow.steps_json or []) if step.get("enabled", True)]
    fallback = None
    by_id = {str(step.get("id")): step for step in enabled}
    last_step = None
    for previous in sent:
        previous_id = str((previous.content_json or {}).get("workflowStepId") or "")
        if previous_id in by_id and not (previous.content_json or {}).get("workflowWaitingFor"):
            last_step = by_id[previous_id]
            break
    if last_step:
        next_id = last_step.get("nextStepId") or last_step.get("next_step_id")
        next_step = by_id.get(str(next_id)) if next_id else None
        if next_step and _matches(next_step, message) and _allowed_by_frequency(next_step, sent, now):
            return _render(next_step)
        if next_step:
            waiting = _waiting_reply(last_step, sent)
            if waiting:
                return waiting
    for step in enabled:
        kind = step.get("triggerType") or step.get("trigger_type")
        if kind == "fallback":
            fallback = step
        elif kind == "condition":
            condition = step.get("condition") or {}
            actual = channel if condition.get("field") == "channel" else message
            expected = str(condition.get("value") or "").casefold()
            actual_normalized = actual.casefold()
            operator = condition.get("operator")
            matched = (
                actual_normalized == expected
                if operator == "equals"
                else actual_normalized.startswith(expected)
                if operator == "starts_with"
                else expected not in actual_normalized
                if operator == "not_contains"
                else expected in actual_normalized
            )
            target = (
                step.get("trueStepId") or step.get("true_step_id")
                if matched
                else step.get("falseStepId") or step.get("false_step_id")
            )
            if target and str(target) in by_id:
                target_step = by_id[str(target)]
                if _allowed_by_frequency(target_step, sent, now):
                    return _render(target_step)
        elif _matches(step, message):
            if _allowed_by_frequency(step, sent, now):
                return _render(step)
    if include_fallback and fallback and _allowed_by_frequency(fallback, sent, now):
        return _render(fallback)
    for previous in sent:
        previous_id = str((previous.content_json or {}).get("workflowStepId") or "")
        if previous_id in by_id:
            waiting = _waiting_reply(by_id[previous_id], sent)
            if waiting:
                return waiting
            break
    return None
