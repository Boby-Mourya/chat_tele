from __future__ import annotations

from uuid import UUID, uuid4

from httpx import AsyncClient
from sqlalchemy import delete, func, select

from northstar_api.database import SessionFactory
from northstar_api.notifications import Notification
from northstar_api.services.notifications import create_notification, project_notification_event


async def _clear_user_notifications(tenant_id: UUID, user_id: UUID) -> None:
    async with SessionFactory() as session:
        await session.execute(
            delete(Notification).where(
                Notification.tenant_id == tenant_id,
                Notification.recipient_user_id == user_id,
            )
        )
        await session.commit()


async def test_notification_inbox_is_scoped_deduplicated_and_readable(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_payload: dict,
) -> None:
    workspace_response = await client.get('/api/v1/workspace', headers=auth_headers)
    assert workspace_response.status_code == 200, workspace_response.text
    workspace = workspace_response.json()
    workspace_id = UUID(workspace['id'])
    tenant_id = UUID(workspace['tenantId'])
    user_id = UUID(session_payload['user']['id'])
    await _clear_user_notifications(tenant_id, user_id)
    secondary_workspace_id = uuid4()

    async with SessionFactory() as session:
        first = await create_notification(
            session,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            recipient_user_id=user_id,
            title='Primary notification',
            body='Visible in the active workspace.',
            dedupe_key='test:primary',
            category='system',
        )
        duplicate = await create_notification(
            session,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            recipient_user_id=user_id,
            title='Duplicate should not be created',
            body='The original row should win.',
            dedupe_key='test:primary',
            category='system',
        )
        assert first.id == duplicate.id
        await create_notification(
            session,
            tenant_id=tenant_id,
            workspace_id=secondary_workspace_id,
            recipient_user_id=user_id,
            title='Other workspace',
            body='Must not leak into the active workspace inbox.',
            dedupe_key='test:secondary',
            category='system',
        )
        await create_notification(
            session,
            tenant_id=tenant_id,
            workspace_id=None,
            recipient_user_id=user_id,
            title='Tenant notice',
            body='Visible in every workspace for this tenant.',
            dedupe_key='test:tenant',
            category='security',
        )
        await session.commit()

        stored = int(
            await session.scalar(
                select(func.count()).select_from(Notification).where(
                    Notification.tenant_id == tenant_id,
                    Notification.recipient_user_id == user_id,
                )
            )
            or 0
        )
        assert stored == 3

    listed = await client.get('/api/v1/notifications', headers=auth_headers)
    assert listed.status_code == 200, listed.text
    titles = {item['title'] for item in listed.json()}
    assert titles == {'Primary notification', 'Tenant notice'}

    count = await client.get('/api/v1/notifications/unread-count', headers=auth_headers)
    assert count.status_code == 200, count.text
    assert count.json()['count'] == 2

    primary = next(item for item in listed.json() if item['title'] == 'Primary notification')
    marked = await client.patch(
        f"/api/v1/notifications/{primary['id']}/read",
        headers=auth_headers,
    )
    assert marked.status_code == 200, marked.text
    assert marked.json()['readAt'] is not None

    count_after_one = await client.get('/api/v1/notifications/unread-count', headers=auth_headers)
    assert count_after_one.json()['count'] == 1

    marked_all = await client.post('/api/v1/notifications/read-all', headers=auth_headers)
    assert marked_all.status_code == 200, marked_all.text
    assert marked_all.json()['updated'] == 1

    final_count = await client.get('/api/v1/notifications/unread-count', headers=auth_headers)
    assert final_count.json()['count'] == 0


async def test_notification_event_projection_targets_workspace_admins(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_payload: dict,
) -> None:
    workspace_response = await client.get('/api/v1/workspace', headers=auth_headers)
    workspace = workspace_response.json()
    workspace_id = UUID(workspace['id'])
    tenant_id = UUID(workspace['tenantId'])
    user_id = UUID(session_payload['user']['id'])
    await _clear_user_notifications(tenant_id, user_id)
    event_id = uuid4()

    async with SessionFactory() as session:
        created = await project_notification_event(
            session,
            event_id=event_id,
            event_type='lead.created.v1',
            tenant_id=tenant_id,
            payload={
                'workspaceId': str(workspace_id),
                'leadId': str(uuid4()),
            },
        )
        await session.commit()
        assert created >= 1
        values = list(
            await session.scalars(
                select(Notification).where(
                    Notification.tenant_id == tenant_id,
                    Notification.recipient_user_id == user_id,
                    Notification.source_event_id == event_id,
                )
            )
        )
        assert len(values) == 1
        assert values[0].category == 'lead'
        assert values[0].workspace_id == workspace_id


async def test_api_key_security_notifications_and_human_only_inbox(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_payload: dict,
) -> None:
    workspace_response = await client.get('/api/v1/workspace', headers=auth_headers)
    workspace = workspace_response.json()
    tenant_id = UUID(workspace['tenantId'])
    user_id = UUID(session_payload['user']['id'])
    await _clear_user_notifications(tenant_id, user_id)

    created = await client.post(
        '/api/v1/workspace/api-keys',
        headers=auth_headers,
        json={'name': 'Notification API Key'},
    )
    assert created.status_code == 201, created.text
    secret = created.json()['secret']
    key_id = created.json()['id']

    inbox = await client.get('/api/v1/notifications', headers=auth_headers)
    assert inbox.status_code == 200, inbox.text
    created_notice = next(item for item in inbox.json() if item['title'] == 'API key created')
    assert created_notice['category'] == 'security'
    assert created_notice['metadata']['apiKeyId'] == key_id

    denied = await client.get(
        '/api/v1/notifications',
        headers={'Authorization': f'Bearer {secret}'},
    )
    assert denied.status_code == 403, denied.text
    assert 'human notification inbox' in denied.json()['error']['message']

    revoked = await client.delete(f'/api/v1/workspace/api-keys/{key_id}', headers=auth_headers)
    assert revoked.status_code == 204, revoked.text
    after_revoke = await client.get('/api/v1/notifications', headers=auth_headers)
    assert after_revoke.status_code == 200, after_revoke.text
    revoked_notice = next(item for item in after_revoke.json() if item['title'] == 'API key revoked')
    assert revoked_notice['severity'] == 'warning'
    assert revoked_notice['metadata']['apiKeyId'] == key_id
