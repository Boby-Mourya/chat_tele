"""WhatsApp message content settings, independent of website appearance."""

import re

from northstar_api.models import Agent


def format_whatsapp_reply(agent: Agent, message: str) -> str:
    # Convert common model Markdown to the markers WhatsApp actually accepts.
    parts = re.split(r"(```[\s\S]*?```|`[^`\n]+`)", message)
    for index, part in enumerate(parts):
        if index % 2:
            # Code examples must remain literal; only the language label is removed.
            parts[index] = re.sub(r"^```[a-zA-Z][\w+-]*\r?\n", "```\n", part)
        else:
            part = re.sub(r"\*\*(.+?)\*\*", r"*\1*", part)
            part = re.sub(r"^#{1,6}[ \t]+(.+)$", r"*\1*", part, flags=re.MULTILINE)
            parts[index] = re.sub(r"\[([^\]]+)\]\((https?://[^\s)]+)\)", r"\1: \2", part)
    body = "".join(parts)
    # Citations remain persisted on the assistant message for audit and UI use,
    # but raw model source markers are not meaningful in a WhatsApp message.
    body = re.sub(r"(?:\s*\[S\d+\])+", "", body, flags=re.IGNORECASE).strip()
    settings = (agent.appearance or {}).get("whatsapp") or {}
    template = settings.get("replyTemplate") or "{message}"
    # Only substitute placeholders in the template, never in model/user content.
    return re.sub(
        r"\{(message|bot_name)\}",
        lambda match: body if match.group(1) == "message" else agent.name,
        template,
    ).strip()
