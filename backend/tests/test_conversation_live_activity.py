from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

from sqlalchemy import select

from northstar_api.database import SessionFactory
from northstar_api.models import Agent, Channel, Conversation, Message, MessageRole
from northstar_api.lead_crm.domain import ChannelProvider
from northstar_api.workers.channel_event_consumer import _persist_message


async def test_latest_message_orders_historical_chats_and_inbound_is_idempotent(client, auth_headers):
    created = await client.post('/api/v1/agents', headers=auth_headers, json={'name': 'Live inbox test'})
    assert created.status_code == 201
    agent_id = UUID(created.json()['id'])
    now = datetime.now(UTC)
    async with SessionFactory() as session:
        agent = await session.get(Agent, agent_id)
        old = Conversation(tenant_id=agent.tenant_id, workspace_id=agent.workspace_id,
            agent_id=agent.id, visitor_id='live-old', visitor_name='Old name', channel=Channel.TELEGRAM,
            updated_at=now - timedelta(days=2))
        newer = Conversation(tenant_id=agent.tenant_id, workspace_id=agent.workspace_id,
            agent_id=agent.id, visitor_id='live-new', visitor_name='Other', channel=Channel.TELEGRAM,
            updated_at=now - timedelta(days=1))
        session.add_all([old, newer])
        await session.flush()
        session.add(Message(tenant_id=agent.tenant_id, workspace_id=agent.workspace_id,
            conversation_id=old.id, sequence=1, role=MessageRole.USER, content='Latest historic message',
            created_at=now))
        await session.commit()
        old_id = old.id
        tenant_id = agent.tenant_id
    response = await client.get('/api/v1/conversations', headers=auth_headers, params={'agent_id': str(agent_id)})
    assert response.status_code == 200
    items = response.json()['items']
    assert items[0]['id'] == str(old_id)
    assert items[0]['preview'] == 'Latest historic message'
    assert datetime.fromisoformat(items[0]['updatedAt'].replace('Z', '+00:00')).replace(tzinfo=UTC) == now
    event = SimpleNamespace(tenant_id=tenant_id, provider=ChannelProvider.TELEGRAM,
        connection_key='live-test', external_event_id='live-event',
        sender=SimpleNamespace(name='Updated name'),
        message=SimpleNamespace(text='New incoming message', external_message_id='live-message'))
    async with SessionFactory() as session:
        conversation = await session.get(Conversation, old_id)
        before = conversation.unread_count or 0
        await _persist_message(session, event=event, conversation=conversation)
        await session.flush()
        await _persist_message(session, event=event, conversation=conversation)
        assert conversation.unread_count == before + 1
        assert conversation.visitor_name == 'Updated name'
        await session.commit()
        messages = list(await session.scalars(select(Message).where(Message.conversation_id == old_id)))
        assert len(messages) == 2
    notifications = await client.get('/api/v1/notifications', headers=auth_headers)
    assert notifications.status_code == 200
    matching = [item for item in notifications.json() if item['actionUrl'] == f'/conversations?selected={old_id}']
    assert len(matching) == 1
