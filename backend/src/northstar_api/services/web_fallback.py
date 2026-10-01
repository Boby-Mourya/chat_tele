"""Small, bounded web fallback used only after approved knowledge misses."""

from __future__ import annotations

from urllib.parse import parse_qs, quote, urlsplit

import httpx
from bs4 import BeautifulSoup

from northstar_api.modules.knowledge.retrieval import Evidence
from northstar_api.services.safe_fetch import fetch_public_text

_SEARCH_URL = "https://api.duckduckgo.com/?format=json&no_html=1&no_redirect=1&q="
_LITE_SEARCH_URL = "https://lite.duckduckgo.com/lite/"
_SEARCH_HEADERS = {"User-Agent": "Mozilla/5.0"}
_FALLBACK_POLICIES = frozenset({"off", "related_only", "public"})


def selected_web_fallback(security: object) -> str:
    """Return the saved dropdown policy; malformed/legacy values fail closed."""
    value = security.get("webFallback") if isinstance(security, dict) else None
    return value if value in _FALLBACK_POLICIES else "off"


def _allowed(url: str, domains: list[str], allow_public: bool) -> bool:
    hostname = (urlsplit(url).hostname or "").lower().rstrip(".")
    return bool(hostname) and (allow_public or any(hostname == domain or hostname.endswith("." + domain) for domain in domains))


def _lite_results(html: str) -> list[tuple[str, str, str]]:
    """Parse DuckDuckGo Lite results and unwrap its outbound redirect URLs."""

    soup = BeautifulSoup(html, "html.parser")
    results: list[tuple[str, str, str]] = []
    for link in soup.select("a.result-link"):
        href = str(link.get("href") or "")
        parsed = urlsplit("https:" + href if href.startswith("//") else href)
        target = parse_qs(parsed.query).get("uddg", [href])[0]
        if urlsplit(target).scheme not in {"http", "https"}:
            continue
        row = link.find_parent("tr")
        snippet_row = row.find_next_sibling("tr") if row else None
        title = link.get_text(" ", strip=True)
        snippet = snippet_row.get_text(" ", strip=True) if snippet_row else ""
        if title and target:
            results.append((title, target, snippet))
    return results


async def related_web_evidence(
    query: str, domains: list[str], *, allow_public: bool = False, max_results: int = 3
) -> list[Evidence]:
    """Use bounded search snippets; fetch pages only from configured/public policy."""
    if not query.strip():
        return []
    payload: dict[str, object] = {}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(8), follow_redirects=False, trust_env=False) as client:
            response = await client.get(_SEARCH_URL + quote(query.strip()))
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError):
        pass

    results: list[tuple[str, str, str]] = []
    abstract_url = str(payload.get("AbstractURL") or "")
    abstract_text = str(payload.get("AbstractText") or "").strip()
    abstract_title = str(payload.get("Heading") or "Web result").strip()
    if abstract_url and abstract_text and _allowed(abstract_url, domains, allow_public):
        results.append((abstract_title, abstract_url, abstract_text))

    def collect(items: object) -> None:
        if not isinstance(items, list):
            return
        for item in items:
            if not isinstance(item, dict):
                continue
            topic = item.get("Topics")
            if topic:
                collect(topic)
            url = str(item.get("FirstURL") or "")
            text = str(item.get("Text") or "").strip()
            if url and text and _allowed(url, domains, allow_public):
                results.append((text.split(" - ", 1)[0], url, text))

    collect(payload.get("RelatedTopics"))
    # Instant Answer topics are an encyclopedia feature, not ranked general
    # search results. Always run general search and put its query-specific
    # matches first; retain Instant Answer entries only as supplementary data.
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(8), follow_redirects=False, trust_env=False
        ) as client:
            response = await client.get(
                _LITE_SEARCH_URL,
                params={"q": query.strip()},
                headers=_SEARCH_HEADERS,
            )
            response.raise_for_status()
            general_results = _lite_results(response.text)
            seen = {url for _, url, _ in general_results}
            results = general_results + [item for item in results if item[1] not in seen]
    except httpx.HTTPError:
        pass
    evidence: list[Evidence] = []
    for title, url, snippet in results:
        if len(evidence) >= max_results or not _allowed(url, domains, allow_public):
            continue
        text = snippet
        try:
            page_text, final_url = await fetch_public_text(url, max_bytes=500_000, max_redirects=3)
            if _allowed(final_url, domains, allow_public) and page_text.strip():
                text = page_text[:20_000]
                url = final_url
        except (ValueError, httpx.HTTPError):
            pass
        evidence.append(
            Evidence(
                kind="web",
                entity_id=url,
                source_id=None,
                title=title[:240] or "Web result",
                url=url,
                text=text,
                score=0.0,
            )
        )
    return evidence
