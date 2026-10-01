from __future__ import annotations

import asyncio
import hashlib
from unittest.mock import AsyncMock

import httpx
import pytest

from northstar_api.modules.knowledge import web_sources as web
from northstar_api.services import crawler, safe_fetch


def urlset(*urls: str) -> str:
    return '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + "".join(
        f"<url><loc>{url.replace('&', '&amp;')}</loc></url>" for url in urls
    ) + "</urlset>"


@pytest.mark.parametrize("suffix", ["?id=1", "?id=2", "/?id=2", "?q=a%2Fb", "?x=2&x=1", "?flag="])
def test_source_url_identity_preserves_query_and_trailing_slash(suffix: str) -> None:
    assert web.canonical_web_url("https://DOCS.example/lesson" + suffix + "#fragment") == (
        "https://docs.example/lesson" + suffix
    )


@pytest.mark.parametrize("url", [
    "/relative", "file:///etc/passwd", "ftp://docs.example/a", "https://u:p@docs.example/a",
    "https://docs.example:8080/a", "https://docs.example/\nsecret", "https://docs.example/" + "x" * 2048,
])
def test_source_url_rejects_unqualified_targets(url: str) -> None:
    with pytest.raises(safe_fetch.UnsafeURL):
        web.canonical_web_url(url)


def test_locations_preserve_order_queries_and_exact_duplicate_accounting() -> None:
    urls = ["https://docs.example/lesson?id=1", "https://docs.example/lesson?id=2", "https://docs.example/lesson?id=1"]
    locations, duplicates = web.sitemap_locations(urlset(*urls), host="docs.example", max_urls=5)
    assert locations == urls[:2]
    assert duplicates == 1


@pytest.mark.parametrize("document", [
    "<urlset>",
    "<sitemapindex><sitemap><loc>https://docs.example/next.xml</loc></sitemap></sitemapindex>",
    "<!DOCTYPE urlset SYSTEM 'http://internal/secret'><urlset/>",
    "<!DOCTYPE urlset [<!ENTITY a 'secret'>]><urlset><url><loc>&a;</loc></url></urlset>",
    "<urlset><url/></urlset>",
    "<urlset><url><loc></loc></url></urlset>",
    "<urlset><url><loc>https://docs.example/a</loc><loc>https://docs.example/b</loc></url></urlset>",
    "<urlset><url><loc><b>https://docs.example/a</b></loc></url></urlset>",
    "<urlset>" + "<x>" * 17 + "</x>" * 17 + "</urlset>",
    urlset("https://attacker.example/a"),
    urlset("https://docs.example:8443/a"),
    urlset("https://u:p@docs.example/a"),
])
def test_sitemap_rejects_unsafe_unsupported_or_incomplete_structure(document: str) -> None:
    with pytest.raises(ValueError):
        web.sitemap_locations(document, host="docs.example", max_urls=5)


def test_sitemap_url_limit_never_silently_clips() -> None:
    with pytest.raises(ValueError, match="no_silent_clipping"):
        web.sitemap_locations(urlset("https://docs.example/a", "https://docs.example/b"), host="docs.example", max_urls=1)


@pytest.mark.asyncio
async def test_success_is_complete_ordered_and_hash_accounted(monkeypatch: pytest.MonkeyPatch) -> None:
    urls = ["https://docs.example/lesson?id=1", "https://docs.example/lesson?id=2"]
    calls: list[str] = []

    async def fetch(url: str, **kwargs: object) -> tuple[str, str]:
        calls.append(url)
        assert kwargs["allowed_hosts"] == frozenset({"docs.example"})
        assert kwargs["allowed_ports"] == frozenset({80, 443})
        return (urlset(*urls) if url.endswith(".xml") else "Answer for " + url), url

    monkeypatch.setattr(web, "fetch_public_text", fetch)
    result = await web.materialize_sitemap("https://docs.example/sitemap.xml", max_urls=5, max_characters=2000)
    assert calls == ["https://docs.example/sitemap.xml", *urls]
    assert [page.final_url for page in result.pages] == urls
    assert result.manifest["status"] == "complete"
    assert result.manifest["fetched_pages"] == 2
    assert result.manifest["projection_sha256"] == hashlib.sha256(result.text.encode()).hexdigest()
    assert all(page["status"] == "fetched" and page["fetched_at"] for page in result.manifest["pages"])
    assert result.text.count("Source page:") == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["empty", "blocked", "http_error", "oversized"])
async def test_partial_crawl_cannot_be_returned_as_usable_text(monkeypatch: pytest.MonkeyPatch, reason: str) -> None:
    urls = [f"https://docs.example/{index}" for index in range(3)]
    calls: list[str] = []

    async def fetch(url: str, **_: object) -> tuple[str, str]:
        calls.append(url)
        if url.endswith(".xml"):
            return urlset(*urls), url
        if url == urls[1]:
            if reason == "blocked":
                raise safe_fetch.UnsafeURL("blocked")
            if reason == "http_error":
                response = httpx.Response(503, request=httpx.Request("GET", url))
                response.raise_for_status()
            return ("" if reason == "empty" else "x" * 2001), url
        return "source answer", url

    monkeypatch.setattr(web, "fetch_public_text", fetch)
    with pytest.raises(web.CrawlIncomplete) as caught:
        await web.materialize_sitemap("https://docs.example/sitemap.xml", max_urls=5, max_characters=2000, concurrency=1)
    manifest = caught.value.manifest
    assert manifest["status"] == "incomplete"
    assert manifest["pages"][2]["status"] == "not_attempted"
    assert urls[2] not in calls
    assert manifest["pages"][1]["status"] in {"blocked", "failed", "character_limit"}


@pytest.mark.asyncio
async def test_projection_budget_includes_headers_and_separators(monkeypatch: pytest.MonkeyPatch) -> None:
    urls = ["https://docs.example/a", "https://docs.example/b"]

    async def fetch(url: str, **_: object) -> tuple[str, str]:
        return (urlset(*urls) if url.endswith(".xml") else "answer"), url

    monkeypatch.setattr(web, "fetch_public_text", fetch)
    exact = len(web.SEPARATOR.join(f"Source page: {url}\n\nanswer" for url in urls))
    result = await web.materialize_sitemap("https://docs.example/sitemap.xml", max_urls=2, max_characters=exact)
    assert len(result.text) == exact
    with pytest.raises(web.CrawlIncomplete):
        await web.materialize_sitemap("https://docs.example/sitemap.xml", max_urls=2, max_characters=exact - 1)


@pytest.mark.asyncio
async def test_oversized_manifest_rejected_before_fetching_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    fetch = AsyncMock(return_value=(urlset("https://docs.example/a", "https://docs.example/b"), "https://docs.example/sitemap.xml"))
    monkeypatch.setattr(web, "fetch_public_text", fetch)
    with pytest.raises(web.CrawlIncomplete):
        await web.materialize_sitemap("https://docs.example/sitemap.xml", max_urls=1, max_characters=2000)
    assert fetch.await_count == 1


@pytest.mark.asyncio
async def test_crawl_timeout_is_not_a_partial_success(monkeypatch: pytest.MonkeyPatch) -> None:
    async def stall(*_: object, **__: object) -> tuple[str, str]:
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    monkeypatch.setattr(web, "fetch_public_text", stall)
    with pytest.raises(web.CrawlIncomplete, match="deadline"):
        await web.materialize_sitemap("https://docs.example/sitemap.xml", max_urls=1, max_characters=2000, total_timeout=0.02)


@pytest.mark.asyncio
async def test_cancellation_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    fetch = AsyncMock(side_effect=asyncio.CancelledError)
    monkeypatch.setattr(web, "fetch_public_text", fetch)
    with pytest.raises(asyncio.CancelledError):
        await web.materialize_sitemap("https://docs.example/sitemap.xml", max_urls=1, max_characters=2000)


@pytest.mark.asyncio
async def test_crawl_concurrency_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    urls = [f"https://docs.example/{index}" for index in range(13)]
    active = peak = 0

    async def fetch(url: str, **_: object) -> tuple[str, str]:
        nonlocal active, peak
        if url.endswith(".xml"):
            return urlset(*urls), url
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0)
        active -= 1
        return "answer", url

    monkeypatch.setattr(web, "fetch_public_text", fetch)
    result = await web.materialize_sitemap("https://docs.example/sitemap.xml", max_urls=20, max_characters=2000, concurrency=3)
    assert len(result.pages) == 13
    assert peak == 3


@pytest.mark.parametrize("function,args", [
    (crawler.crawl_page, ("http://127.0.0.1/",)),
    (crawler.discover_sitemap, ("https://docs.example/",)),
    (crawler.crawl_website, ("https://docs.example/",)),
    (crawler.take_screenshot, ("https://docs.example/", "x.png")),
])
def test_legacy_crawler_entrypoints_fail_before_network(function: object, args: tuple[str, ...], monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*_: object, **__: object) -> None:
        raise AssertionError("network must not be attempted")

    monkeypatch.setattr("socket.getaddrinfo", forbidden)
    monkeypatch.setattr("socket.socket.connect", forbidden)
    with pytest.raises(crawler.CrawlerCapabilityDisabled):
        function(*args)


@pytest.mark.asyncio
@pytest.mark.parametrize("target", ["https://other.example/page", "https://docs.example:8443/page", "http://metadata.internal/latest"])
async def test_redirect_scope_is_checked_before_dns_or_connection(monkeypatch: pytest.MonkeyPatch, target: str) -> None:
    lookups: list[str] = []
    requests: list[str] = []

    async def lookup(host: str, _: int) -> tuple[str, ...]:
        lookups.append(host)
        return ("93.184.216.34",)

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        return httpx.Response(302, headers={"location": target})

    monkeypatch.setattr(safe_fetch, "_lookup_addresses", lookup)
    monkeypatch.setattr(safe_fetch, "_new_transport", lambda: httpx.MockTransport(handler))
    with pytest.raises(safe_fetch.UnsafeURL):
        await safe_fetch.fetch_public_text("https://docs.example/start", allowed_hosts=frozenset({"docs.example"}), allowed_ports=web.WEB_PORTS)
    assert lookups == ["docs.example"]
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("grant", [{"allowed_hosts": frozenset()}, {"allowed_ports": frozenset()}])
async def test_empty_scope_denies_before_dns(monkeypatch: pytest.MonkeyPatch, grant: dict[str, frozenset]) -> None:
    lookup = AsyncMock(side_effect=AssertionError("must not resolve"))
    monkeypatch.setattr(safe_fetch, "_lookup_addresses", lookup)
    with pytest.raises(safe_fetch.UnsafeURL):
        await safe_fetch.fetch_public_text("https://docs.example/", **grant)
    lookup.assert_not_awaited()


@pytest.mark.asyncio
async def test_total_fetch_deadline_includes_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    async def stall(*_: object) -> tuple[str, ...]:
        await asyncio.Event().wait()
        return ()

    monkeypatch.setattr(safe_fetch, "_lookup_addresses", stall)
    with pytest.raises(TimeoutError):
        await safe_fetch.fetch_public_text("https://docs.example/", total_timeout=0.02)


@pytest.mark.asyncio
@pytest.mark.parametrize("body,kwargs", [(b"\xff", {}), (b"1234", {"max_bytes": 3})])
async def test_invalid_text_or_oversized_response_fails_instead_of_losing_content(monkeypatch: pytest.MonkeyPatch, body: bytes, kwargs: dict[str, int]) -> None:
    monkeypatch.setattr(safe_fetch, "_lookup_addresses", AsyncMock(return_value=("93.184.216.34",)))
    monkeypatch.setattr(safe_fetch, "_new_transport", lambda: httpx.MockTransport(
        lambda _: httpx.Response(200, headers={"content-type": "text/plain; charset=utf-8"}, content=body)
    ))
    with pytest.raises(ValueError):
        await safe_fetch.fetch_public_text("https://docs.example/", **kwargs)


@pytest.mark.asyncio
@pytest.mark.parametrize("kwargs", [{"max_bytes": 0}, {"max_bytes": True}, {"max_redirects": -1}, {"max_redirects": True}, {"total_timeout": 0}, {"total_timeout": float("nan")}, {"total_timeout": float("inf")}])
async def test_invalid_transport_budgets_rejected(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        await safe_fetch.fetch_public_text("https://docs.example/", **kwargs)


@pytest.mark.asyncio
async def test_port_zero_rejected_before_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    lookup = AsyncMock(side_effect=AssertionError("must not resolve"))
    monkeypatch.setattr(safe_fetch, "_lookup_addresses", lookup)
    with pytest.raises(safe_fetch.UnsafeURL):
        await safe_fetch.fetch_public_text("http://docs.example:0/", allowed_ports=web.WEB_PORTS)
    with pytest.raises(safe_fetch.UnsafeURL):
        web.canonical_web_url("http://docs.example:0/")
    lookup.assert_not_awaited()


@pytest.mark.asyncio
async def test_https_downgrade_is_rejected_before_second_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    lookup = AsyncMock(return_value=("93.184.216.34",))
    monkeypatch.setattr(safe_fetch, "_lookup_addresses", lookup)
    monkeypatch.setattr(safe_fetch, "_new_transport", lambda: httpx.MockTransport(
        lambda _: httpx.Response(302, headers={"location": "http://docs.example/unsafe"})
    ))
    with pytest.raises(safe_fetch.UnsafeURL, match="downgrade"):
        await safe_fetch.fetch_public_text("https://docs.example/start")
    assert lookup.await_count == 1


@pytest.mark.asyncio
async def test_compression_is_rejected_before_reading_body(monkeypatch: pytest.MonkeyPatch) -> None:
    class NeverRead(httpx.AsyncByteStream):
        async def __aiter__(self):
            raise AssertionError("compressed bytes must not be read or expanded")
            yield b"unreachable"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["accept-encoding"] == "identity"
        return httpx.Response(200, headers={"content-type": "text/plain", "content-encoding": "gzip"}, stream=NeverRead())

    monkeypatch.setattr(safe_fetch, "_lookup_addresses", AsyncMock(return_value=("93.184.216.34",)))
    monkeypatch.setattr(safe_fetch, "_new_transport", lambda: httpx.MockTransport(handler))
    with pytest.raises(ValueError, match="Compressed"):
        await safe_fetch.fetch_public_text("https://docs.example/a")
