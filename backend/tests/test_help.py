from __future__ import annotations

from httpx import AsyncClient


async def test_help_requires_authentication(client: AsyncClient) -> None:
    response = await client.get('/api/v1/help')
    assert response.status_code == 401


async def test_help_home_categories_article_search_and_feedback(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    home = await client.get('/api/v1/help', headers=auth_headers)
    assert home.status_code == 200, home.text
    payload = home.json()
    assert payload['categories']
    assert payload['support']['email']
    slugs = [item['slug'] for item in payload['categories']]
    assert 'getting-started' in slugs
    assert 'agents' in slugs

    article = await client.get('/api/v1/help/articles/create-agent', headers=auth_headers)
    assert article.status_code == 200, article.text
    article_payload = article.json()
    assert article_payload['slug'] == 'create-agent'
    assert article_payload['bodyMarkdown']
    assert set(article_payload['audienceRoles']) == {'owner', 'admin'}
    assert 'previous' in article_payload
    assert 'next' in article_payload

    search = await client.get('/api/v1/help/search', headers=auth_headers, params={'q': 'create agent'})
    assert search.status_code == 200, search.text
    search_payload = search.json()
    assert search_payload['items']
    assert search_payload['items'][0]['slug'] == 'create-agent'

    event = await client.post(
        '/api/v1/help/events',
        headers=auth_headers,
        json={
            'eventType': 'search_click',
            'articleId': search_payload['items'][0]['id'],
            'query': 'create agent',
        },
    )
    assert event.status_code == 204, event.text

    feedback_url = f"/api/v1/help/articles/{article_payload['id']}/feedback"
    first = await client.post(feedback_url, headers=auth_headers, json={'helpful': False, 'reason': 'missing_steps', 'comment': 'Add more setup detail.'})
    assert first.status_code == 200, first.text
    second = await client.post(feedback_url, headers=auth_headers, json={'helpful': True})
    assert second.status_code == 200, second.text
    assert second.json()['helpful'] is True


async def test_help_support_request_filters_diagnostics_and_uses_workspace_destination(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    workspace = await client.get('/api/v1/workspace', headers=auth_headers)
    assert workspace.status_code == 200, workspace.text
    original = workspace.json()
    branded = {
        **original['whiteLabel'],
        'supportEmail': 'helpdesk@example.com',
        'supportUrl': 'https://example.com/support',
    }
    changed = await client.patch('/api/v1/workspace', headers=auth_headers, json={'whiteLabel': branded})
    assert changed.status_code == 200, changed.text
    try:
        created = await client.post(
            '/api/v1/help/support-requests',
            headers=auth_headers,
            json={
                'category': 'knowledge',
                'subject': 'Knowledge source is processing',
                'message': 'The source has remained in processing and I need help diagnosing it.',
                'contextPath': '/agents/example/knowledge',
                'includeDiagnostics': True,
                'diagnostics': {
                    'platform': 'test',
                    'language': 'en-US',
                    'apiKey': 'must-not-be-stored',
                    'token': 'must-not-be-stored',
                },
            },
        )
        assert created.status_code == 201, created.text
        payload = created.json()
        assert payload['supportDestination'] == 'helpdesk@example.com'
        assert payload['diagnostics']['platform'] == 'test'
        assert 'apiKey' not in payload['diagnostics']
        assert 'token' not in payload['diagnostics']

        listed = await client.get('/api/v1/help/support-requests', headers=auth_headers)
        assert listed.status_code == 200, listed.text
        assert any(item['id'] == payload['id'] for item in listed.json())

        detail = await client.get(f"/api/v1/help/support-requests/{payload['id']}", headers=auth_headers)
        assert detail.status_code == 200, detail.text
    finally:
        restored = await client.patch('/api/v1/workspace', headers=auth_headers, json={'whiteLabel': original['whiteLabel']})
        assert restored.status_code == 200, restored.text
