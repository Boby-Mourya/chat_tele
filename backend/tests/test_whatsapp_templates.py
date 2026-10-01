import json

import httpx
import pytest

from northstar_api.config import Settings
from northstar_api.services.whatsapp import WhatsAppCloudClient
from northstar_api.services.whatsapp_templates import build_template, template_fields


def test_named_and_positional_template_parameters_are_built_server_side():
    template = {
        "name": "order",
        "language": "en",
        "components": [
            {"type": "HEADER", "format": "TEXT", "text": "Order {{1}}"},
            {"type": "BODY", "text": "Hello {{customer}}, hello {{customer}}"},
        ],
    }
    payload, rendered = build_template(template, ["42", "Sam"])
    assert rendered == "Order 42\nHello Sam, hello Sam"
    assert payload["components"][0]["parameters"] == [{"type": "text", "text": "42"}]
    assert payload["components"][1]["parameters"] == [
        {"type": "text", "text": "Sam", "parameter_name": "customer"}
    ]
    with pytest.raises(ValueError, match="requires 2"):
        build_template(template, ["42"])


def test_media_templates_are_not_misrepresented_as_text_templates():
    with pytest.raises(ValueError, match="media and button"):
        template_fields({"components": [{"type": "HEADER", "format": "IMAGE"}]})


async def test_graph_template_lookup_paginates_and_send_uses_template_payload():
    observed = []

    def handle(request):
        observed.append(request)
        assert request.headers["Authorization"] == "Bearer test-token"
        if request.method == "POST":
            body = json.loads(request.content)
            assert body["type"] == "template"
            assert body["template"] == {"name": "hello", "language": {"code": "en"}, "components": []}
            return httpx.Response(200, json={"messages": [{"id": "wamid.template"}]})
        if request.url.params.get("after"):
            return httpx.Response(
                200, json={"data": [{"name": "hello", "language": "en", "status": "APPROVED"}]}
            )
        return httpx.Response(
            200,
            json={
                "data": [{"name": "rejected", "status": "REJECTED"}],
                "paging": {"next": "ignored-provider-url", "cursors": {"after": "cursor"}},
            },
        )

    client = WhatsAppCloudClient(
        Settings(
            **{
                "app_env": "test",
                "meta_app_id": "123",
                "meta_app_secret": "test-app-secret",
                "meta_whatsapp_configuration_id": "456",
                "meta_whatsapp_webhook_verify_token": "webhook-verify-token-used-only-in-tests",
                "meta_whatsapp_token_encryption_key": "test-only-encryption-key-at-least-32-characters",
            }
        ),
        transport=httpx.MockTransport(handle),
    )
    templates = await client.list_templates("test-token", waba_id="555")
    assert len(templates) == 1
    message_id = await client.send_template(
        "test-token",
        phone_number_id="777",
        to="15550101",
        template={"name": "hello", "language": {"code": "en"}, "components": []},
    )
    assert message_id == "wamid.template"
    assert len(observed) == 3
