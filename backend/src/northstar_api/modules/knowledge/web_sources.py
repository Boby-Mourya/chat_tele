"""Bounded, fail-closed sitemap materialization through the shared safe transport.

This adapter records visible-text hashes and locators, not full HTML snapshots.
Nested sitemap indexes and browser rendering are deliberately not supported.
"""

from __future__ import annotations

import asyncio
import hashlib
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, NoReturn
from xml.parsers import expat

import httpx

from northstar_api.services.safe_fetch import UnsafeURL, fetch_public_text

SITEMAP_NAMESPACE = "http://www.sitemaps.org/schemas/sitemap/0.9"
WEB_PORTS = frozenset({80, 443})
SEPARATOR = "\n\n---\n\n"


class CrawlIncomplete(ValueError):
    """No searchable candidate may be published from this crawl."""

    def __init__(self, reason: str, manifest: dict[str, Any]) -> None:
        self.manifest = manifest
        self.manifest.update(status="incomplete", reason=reason)
        super().__init__(f"Sitemap ingestion incomplete: {reason}; no partial content was published")


@dataclass(frozen=True, slots=True)
class WebPage:
    requested_url: str
    final_url: str
    text: str
    fetched_at: str

    def manifest_entry(self) -> dict[str, Any]:
        return {
            "requested_url": self.requested_url,
            "final_url": self.final_url,
            "status": "fetched",
            "fetched_at": self.fetched_at,
            "text_sha256": hashlib.sha256(self.text.encode("utf-8")).hexdigest(),
            "characters": len(self.text),
        }


@dataclass(frozen=True, slots=True)
class SitemapMaterialization:
    text: str
    sitemap_url: str
    pages: tuple[WebPage, ...]
    manifest: dict[str, Any]


def canonical_web_url(value: str) -> str:
    """Preserve query order, encoded values and trailing slashes; discard only fragments."""
    if not isinstance(value, str) or len(value) > 2048 or any(ord(c) < 32 for c in value):
        raise UnsafeURL("Source URL is invalid or exceeds the URL length limit")
    try:
        url = httpx.URL(value)
        hostname = url.raw_host.decode("ascii").lower().rstrip(".")
    except (ValueError, UnicodeError, httpx.InvalidURL) as exc:
        raise UnsafeURL("Source URL is malformed") from exc
    if url.scheme not in {"http", "https"} or not hostname or url.userinfo or "%" in hostname:
        raise UnsafeURL("Only absolute HTTP(S) source URLs without credentials are supported")
    port = url.port if url.port is not None else (443 if url.scheme == "https" else 80)
    if port not in WEB_PORTS:
        raise UnsafeURL("Sitemap source ports are restricted to 80 and 443")
    return str(url.copy_with(host=hostname, fragment=None))


def sitemap_locations(text: str, *, host: str, max_urls: int) -> tuple[list[str], int]:
    """Parse a bounded urlset without DTDs, entities, recursion or remote includes."""
    if len(text) > 1_000_000:
        raise ValueError("sitemap_size_limit")
    parser = expat.ParserCreate(namespace_separator="}")
    stack: list[str] = []
    locations: list[str] = []
    seen: set[str] = set()
    current: list[str] = []
    location_count = 0
    duplicate_count = 0
    location_length = 0
    root_namespace = ""

    def reject_declaration(*_: object) -> NoReturn:
        raise ValueError("sitemap_DTD_and_entities_not_supported")

    def start(name: str, _: dict[str, str]) -> None:
        nonlocal location_count, location_length, root_namespace
        if not stack:
            if name not in {"urlset", f"{SITEMAP_NAMESPACE}}}urlset"}:
                raise ValueError("only_urlset_supported_not_sitemap_indexes")
            root_namespace = name.rsplit("}", 1)[0] + "}" if "}" in name else ""
        stack.append(name)
        if len(stack) > 16:
            raise ValueError("sitemap_depth_limit")
        if len(stack) == 2 and name == root_namespace + "url":
            location_count = 0
        if len(stack) == 3 and stack[1:] == [root_namespace + "url", root_namespace + "loc"]:
            location_count += 1
            if location_count > 1:
                raise ValueError("multiple_locations_in_one_url")
            current.clear()
            location_length = 0
        elif len(stack) > 3 and stack[2] == root_namespace + "loc":
            raise ValueError("nested_markup_in_location")

    def data(value: str) -> None:
        nonlocal location_length
        if len(stack) == 3 and stack[1:] == [root_namespace + "url", root_namespace + "loc"]:
            location_length += len(value)
            if location_length > 2048:
                raise ValueError("location_length_limit")
            current.append(value)

    def end(name: str) -> None:
        nonlocal duplicate_count
        if len(stack) == 3 and stack[1:] == [root_namespace + "url", root_namespace + "loc"]:
            location = canonical_web_url("".join(current).strip())
            if httpx.URL(location).host != host:
                raise UnsafeURL("Sitemap contains an out-of-scope host")
            if location in seen:
                duplicate_count += 1
            else:
                seen.add(location)
                locations.append(location)
                if len(locations) > max_urls:
                    raise ValueError("sitemap_url_limit_no_silent_clipping")
        if len(stack) == 2 and name == root_namespace + "url" and location_count != 1:
            raise ValueError("url_requires_exactly_one_location")
        stack.pop()

    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.CharacterDataHandler = data
    parser.StartDoctypeDeclHandler = reject_declaration
    parser.EntityDeclHandler = reject_declaration
    parser.ExternalEntityRefHandler = reject_declaration
    parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
    try:
        parser.Parse(text, True)
    except expat.ExpatError as exc:
        raise ValueError("malformed_sitemap_XML") from exc
    if not locations:
        raise ValueError("sitemap_has_no_page_locations")
    return locations, duplicate_count


async def materialize_sitemap(
    url: str,
    *,
    max_urls: int,
    max_characters: int,
    concurrency: int = 5,
    total_timeout: float = 120.0,
) -> SitemapMaterialization:
    """Account for every selected page; reject failures and limits before indexing."""
    for name, value, ceiling in (("max_urls", max_urls, 1000), ("concurrency", concurrency, 5)):
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= ceiling:
            raise ValueError(f"{name} must be an integer from 1 to {ceiling}")
    if isinstance(max_characters, bool) or not isinstance(max_characters, int) or max_characters < 1:
        raise ValueError("max_characters must be a positive integer")
    if isinstance(total_timeout, bool) or not math.isfinite(total_timeout) or total_timeout <= 0:
        raise ValueError("total_timeout must be positive and finite")
    requested = canonical_web_url(url)
    host = httpx.URL(requested).host
    grant = frozenset({host})
    manifest: dict[str, Any] = {
        "version": 1,
        "representation": "guarded-visible-text",
        "requested_sitemap_url": requested,
        "started_at": datetime.now(UTC).isoformat(),
        "status": "running",
        "max_urls": max_urls,
        "max_characters": max_characters,
        "pages": [],
    }
    pages: list[WebPage] = []
    sections: list[str] = []
    characters = 0

    async def fetch_page(location: str) -> WebPage | Exception:
        try:
            text, final = await fetch_public_text(
                location, max_bytes=500_000, allowed_hosts=grant, allowed_ports=WEB_PORTS
            )
            final = canonical_web_url(final)
            if httpx.URL(final).host != host:
                raise UnsafeURL("Page escaped its source scope")
            if not text.strip():
                raise ValueError("empty_page_text")
            return WebPage(location, final, text.strip(), datetime.now(UTC).isoformat())
        except Exception as exc:
            # Cancellation is a BaseException and must propagate, not become success.
            return exc

    try:
        async with asyncio.timeout(total_timeout):
            sitemap, final_url = await fetch_public_text(
                requested, max_bytes=1_000_000, allowed_hosts=grant, allowed_ports=WEB_PORTS
            )
            final_url = canonical_web_url(final_url)
            if httpx.URL(final_url).host != host:
                raise UnsafeURL("Sitemap escaped its source scope")
            manifest["sitemap_url"] = final_url
            manifest["sitemap_text_sha256"] = hashlib.sha256(sitemap.encode("utf-8")).hexdigest()
            locations, duplicates = sitemap_locations(sitemap, host=host, max_urls=max_urls)
            manifest["duplicate_locations"] = duplicates
            manifest["pages"] = [{"requested_url": item, "status": "not_attempted"} for item in locations]
            for offset in range(0, len(locations), concurrency):
                batch = locations[offset : offset + concurrency]
                results = await asyncio.gather(*(fetch_page(location) for location in batch))
                failed = False
                for index, result in enumerate(results, offset):
                    if isinstance(result, Exception):
                        entry = manifest["pages"][index]
                        entry["status"] = "blocked" if isinstance(result, UnsafeURL) else "failed"
                        entry["error_type"] = type(result).__name__
                        if isinstance(result, httpx.HTTPStatusError):
                            entry["http_status"] = result.response.status_code
                        failed = True
                        continue
                    manifest["pages"][index] = result.manifest_entry()
                    section = f"Source page: {result.final_url}\n\n{result.text}"
                    size = len(section) + (len(SEPARATOR) if sections else 0)
                    if size > max_characters - characters:
                        manifest["pages"][index]["status"] = "character_limit"
                        failed = True
                        continue
                    sections.append(section)
                    pages.append(result)
                    characters += size
                if failed:
                    raise CrawlIncomplete("page_failure_or_character_limit", manifest)
            text = SEPARATOR.join(sections)
            manifest.update(
                status="complete", completed_at=datetime.now(UTC).isoformat(),
                fetched_pages=len(pages), characters=len(text),
                projection_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            )
            return SitemapMaterialization(text, final_url, tuple(pages), manifest)
    except CrawlIncomplete:
        raise
    except TimeoutError as exc:
        raise CrawlIncomplete("crawl_deadline_exceeded", manifest) from exc
    except (ValueError, httpx.HTTPError) as exc:
        manifest["error_type"] = type(exc).__name__
        if isinstance(exc, ValueError) and not isinstance(exc, httpx.HTTPError):
            manifest["error_reason"] = str(exc)[:240]
        # Do not copy provider exception strings (which can contain credentials).
        raise CrawlIncomplete("sitemap_rejected_or_unavailable", manifest) from exc
