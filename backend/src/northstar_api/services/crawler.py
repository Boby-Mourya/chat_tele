"""Compatibility utilities for the retired, unrestricted browser crawler.

Network entrypoints fail before I/O. Knowledge ingestion uses safe_fetch and the
bounded sitemap adapter; rendering requires a separately qualified egress worker.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TypedDict
from urllib.parse import urlparse

from northstar_api.modules.knowledge.web_sources import canonical_web_url
from northstar_api.services.safe_fetch import UnsafeURL

MAX_PAGES = 300
REQUEST_TIMEOUT = 15
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; NEXORA-Bot/1.0)"}


class CrawledPage(TypedDict):
    url: str
    title: str
    text: str
    links: list[str]


class CrawlerCapabilityDisabled(UnsafeURL):
    """The legacy transport must not bypass the application's egress boundary."""


def normalize_url(url: str) -> str:
    return canonical_web_url(url)


def is_same_domain(base_url: str, target_url: str) -> bool:
    try:
        base = urlparse(normalize_url(base_url))
        target = urlparse(normalize_url(target_url))
    except (ValueError, TypeError):
        return False
    return base.netloc == target.netloc


def is_valid_page_url(url: str) -> bool:
    try:
        parsed = urlparse(normalize_url(url))
    except (ValueError, TypeError):
        return False
    return not parsed.path.lower().endswith(
        (".pdf", ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".zip", ".rar",
         ".mp4", ".mp3", ".avi", ".mov", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx")
    )


def crawl_page(url: str) -> CrawledPage:
    raise CrawlerCapabilityDisabled("Legacy crawling is disabled; use the guarded knowledge ingestion API")


def discover_sitemap(base_url: str) -> list[str]:
    raise CrawlerCapabilityDisabled("Automatic sitemap discovery is disabled; submit an explicit sitemap URL")


def crawl_website(start_url: str, max_pages: int = MAX_PAGES) -> list[CrawledPage]:
    raise CrawlerCapabilityDisabled("Legacy crawling is disabled; use the guarded knowledge ingestion API")


def take_screenshot(url: str, filename: str) -> str:
    raise CrawlerCapabilityDisabled("Browser rendering is disabled until an isolated egress worker is qualified")


def save_pages(pages: list[CrawledPage], filename: str = "website.json") -> str:
    """Retain the local JSON export helper, without accepting a caller-selected path."""
    if not filename or "/" in filename or "\\" in filename or Path(filename).name != filename:
        raise ValueError("filename must be a single JSON file name")
    if Path(filename).suffix.lower() != ".json":
        raise ValueError("filename must end with .json")
    output_dir = Path("data/raw")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / filename
    if output_file.is_symlink():
        raise ValueError("Refusing a symlink export target")
    output_file.write_text(json.dumps(pages, indent=2, ensure_ascii=False), encoding="utf-8")
    return str(output_file)
