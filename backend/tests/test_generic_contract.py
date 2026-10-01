"""Contract checks perform no DNS lookup or third-party request."""

from __future__ import annotations

import pytest

from northstar_api.lead_crm.generic_contract import (
    assert_same_origin,
    configured_capabilities,
    destination_url,
    request_options,
    validate_headers,
)

BASE = {"baseUrl": "https://crm.example/api/v1", "createPath": "/leads"}


def test_create_only_has_no_phantom_capabilities():
    caps = configured_capabilities(BASE)
    assert caps["create"]
    assert not caps["update"] and not caps["upsert"] and not caps["readBack"]


def test_optional_operations_require_valid_contracts():
    caps = configured_capabilities({**BASE, "updatePath": "leads/{id}", "getPath": "leads/{id}", "upsertPath": "leads/upsert"})
    assert caps["create"] and caps["update"] and caps["upsert"] and caps["readBack"]


@pytest.mark.parametrize("configuration", [{}, {"baseUrl": "http://crm.example"}, {**BASE, "updatePath": "leads"}, {**BASE, "successStatusCodes": [500]}])
def test_invalid_legacy_configuration_advertises_nothing(configuration):
    assert not any(configured_capabilities(configuration).values())


def test_existing_base_path_convention_and_query_are_preserved():
    assert destination_url(BASE, "createPath") == "https://crm.example/api/v1/leads"
    assert destination_url({**BASE, "getPath": "leads?record={id}"}, "getPath", external_id="a/b?#") == "https://crm.example/api/v1/leads?record=a%2Fb%3F%23"


@pytest.mark.parametrize("path", ["https://other.example/leads", "//other.example/leads", "http://crm.example/leads", "file:///tmp/data", "\\\\other.example\\leads", "leads#fragment", "../leads", "%2e%2e/leads", "leads%0d%0aX-Test:yes", " leads", "leads\n"])
def test_unsafe_paths_rejected_before_network(path):
    with pytest.raises(ValueError):
        destination_url({**BASE, "createPath": path}, "createPath")


@pytest.mark.parametrize("base", ["https://user:secret@crm.example", "https://crm.example:0", "https://crm.example:99999", "https://crm.example/api?secret=x", "https://crm.example/api#x", "https://crm.example/\n", "https://crm.example%00/", "", None])
def test_unsafe_base_rejected(base):
    with pytest.raises(ValueError):
        destination_url({**BASE, "baseUrl": base}, "createPath")


def test_encoded_record_id_cannot_replace_host_or_query():
    result = destination_url({**BASE, "getPath": "leads/{id}"}, "getPath", external_id="https://other.example/x?y=1#z")
    assert result == "https://crm.example/api/v1/leads/https%3A%2F%2Fother.example%2Fx%3Fy%3D1%23z"


@pytest.mark.parametrize("record_id", ["", ".", "..", "bad\nvalue", "x" * 1025])
def test_invalid_record_id_rejected(record_id):
    with pytest.raises(ValueError):
        destination_url({**BASE, "getPath": "leads/{id}"}, "getPath", external_id=record_id)


@pytest.mark.parametrize("target", ["https://other.example/api", "https://crm.example:444/api", "http://crm.example/api", "https://user@crm.example/api"])
def test_credential_origin_rechecked(target):
    with pytest.raises(ValueError):
        assert_same_origin(BASE, target)


def test_equivalent_default_https_port():
    assert_same_origin(BASE, "https://CRM.example:443/api")


@pytest.mark.parametrize("headers", [{"Host": "other.example"}, {"Content-Length": "0"}, {"Transfer-Encoding": "chunked"}, {"X-Forwarded-Host": "other.example"}, {"Proxy-Authorization": "secret"}, {"X-Key": "first", "x-key": "second"}, {"X-Key\n": "value"}, {"X-Key": "value\r\nInjected: yes"}])
def test_header_smuggling_rejected(headers):
    with pytest.raises(ValueError):
        validate_headers(headers)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), "NaN", True, {}, None])
def test_nonfinite_or_invalid_timeout_rejected(value):
    with pytest.raises(ValueError):
        request_options({"timeoutSeconds": value})


@pytest.mark.parametrize("codes", [[500], [301], [199], [True], ["200"], [], "200"])
def test_error_status_cannot_be_configured_as_success(codes):
    with pytest.raises(ValueError):
        request_options({"successStatusCodes": codes})


@pytest.mark.parametrize("name", ["Authorization", "Cookie", "X-Northstar-Signature", "Host", "Content-Type"])
def test_idempotency_header_cannot_overwrite_security_headers(name):
    with pytest.raises(ValueError):
        request_options({"idempotencyHeader": name})


@pytest.mark.parametrize("configuration", [
    {**BASE, "getPath": "leads/{id}/{unexpected}"},
    {**BASE, "headers": []},
    {**BASE, "auth": []},
])
def test_malformed_optional_contracts_advertise_nothing(configuration):
    assert not any(configured_capabilities(configuration).values())
