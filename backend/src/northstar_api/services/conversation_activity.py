"""Use persisted message times to recover activity for older channel conversations."""
from datetime import UTC

from sqlalchemy import case, func, select

from northstar_api.models import Conversation, Message


def conversation_activity_order():
    last_message_at = select(func.max(Message.created_at)).where(
        Message.conversation_id == Conversation.id,
        Message.tenant_id == Conversation.tenant_id,
        Message.workspace_id == Conversation.workspace_id,
    ).correlate(Conversation).scalar_subquery()
    return case(
        (last_message_at > Conversation.updated_at, last_message_at),
        else_=Conversation.updated_at,
    )


def conversation_activity_time(conversation: Conversation):
    values = [conversation.updated_at, *(message.created_at for message in conversation.messages)]
    return max(value.replace(tzinfo=UTC) if value.tzinfo is None else value for value in values)
