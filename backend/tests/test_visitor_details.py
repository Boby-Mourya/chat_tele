from types import SimpleNamespace

from starlette.requests import Request

from northstar_api.schemas import WidgetSessionCreate
from northstar_api.services import visitor_details


def test_capture_utm_and_ignore_forged_ip(monkeypatch):
    monkeypatch.setattr(visitor_details, "get_settings", lambda: SimpleNamespace(visitor_trusted_proxy_cidrs=""))
    request = Request({"type": "http", "client": ("8.8.8.8", 123), "headers": [(b"x-forwarded-for", b"1.1.1.1")]})
    details = visitor_details.capture_visitor_details(request, WidgetSessionCreate(page_url="https://example.com/course?utm_source=ad&utm_campaign=summer", visitor_details={"ipAddress": "9.9.9.9"}))
    assert details["ip_address"] == "8.8.8.8"
    assert details["utm_source"] == "ad"
    assert details["page_slug"] == "/course"


def test_trusted_proxy_chain_uses_nearest_untrusted_address(monkeypatch):
    monkeypatch.setattr(visitor_details, "get_settings", lambda: SimpleNamespace(visitor_trusted_proxy_cidrs="172.28.0.0/16"))
    request = Request({"type": "http", "client": ("172.28.0.5", 123), "headers": [(b"x-forwarded-for", b"9.9.9.9, 8.8.8.8, 172.28.0.3")]})
    assert visitor_details.capture_visitor_details(request, WidgetSessionCreate())["ip_address"] == "8.8.8.8"


async def test_geolocation_failure_does_not_block_capture(monkeypatch):
    import httpx
    monkeypatch.setattr(visitor_details, "get_settings", lambda: SimpleNamespace(visitor_geoip_enabled=True))
    async def failed(*args, **kwargs):
        raise httpx.ConnectTimeout("lookup unavailable")
    monkeypatch.setattr(httpx.AsyncClient, "get", failed)
    result = await visitor_details.enrich_location({"ip_address": "8.8.8.8", "utm_source": "ad"})
    assert result == {"ip_address": "8.8.8.8", "utm_source": "ad"}


async def test_geolocation_returns_approximate_location(monkeypatch):
    import httpx
    monkeypatch.setattr(visitor_details, "get_settings", lambda: SimpleNamespace(visitor_geoip_enabled=True))
    async def success(*args, **kwargs):
        return httpx.Response(200, request=httpx.Request("GET", "https://ipwho.is/8.8.8.8"), json={"success": True, "city": "Sample city", "region": "Sample region", "country": "Sample country"})
    monkeypatch.setattr(httpx.AsyncClient, "get", success)
    result = await visitor_details.enrich_location({"ip_address": "8.8.8.8"})
    assert result["location"] == "Sample city, Sample region, Sample country"
