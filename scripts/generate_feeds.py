#!/usr/bin/env python3
"""Build stable RSS 2.0 feeds from public product release-note pages."""
from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import UTC, datetime
from email.utils import format_datetime
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

import requests
from bs4 import BeautifulSoup, Tag

ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / "data" / "state.json"
FEED_DIR = ROOT / "docs" / "feeds"
USER_AGENT = "ai-release-notes-rss/1.0 (+https://github.com/Zytinc/ai-release-notes-rss)"
MAX_HISTORY = 80

SOURCES = {
    "claude_apps": {
        "name": "Claude Apps Release Notes",
        "url": "https://support.claude.com/en/articles/12138966-release-notes",
        "feed_file": "claude-apps-release-notes.xml",
        "description": "Claude Apps、Desktop、Mobile、Cowork、Connectors 等产品更新。",
    },
    "gemini_api": {
        "name": "Gemini API Changelog",
        "url": "https://ai.google.dev/gemini-api/docs/changelog",
        "feed_file": "gemini-api-changelog.xml",
        "description": "Gemini API 的模型、工具调用、平台与弃用更新。",
    },
}

DATE_PATTERNS = (
    "%B %d, %Y",
    "%b %d, %Y",
    "%B %Y",
    "%b %Y",
)


def utcnow() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("\xa0", " ")).strip()


def parse_date(value: str) -> datetime | None:
    value = clean_text(value)
    value = re.sub(r"(\d{1,2})(st|nd|rd|th)", r"\1", value, flags=re.I)
    for pattern in DATE_PATTERNS:
        try:
            parsed = datetime.strptime(value, pattern)
            if pattern in ("%B %Y", "%b %Y"):
                parsed = parsed.replace(day=1)
            return parsed.replace(tzinfo=UTC)
        except ValueError:
            pass
    return None


def fetch_soup(url: str) -> BeautifulSoup:
    response = requests.get(
        url,
        headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"},
        timeout=40,
    )
    response.raise_for_status()
    return BeautifulSoup(response.text, "html.parser")


def text_until_next_heading(heading: Tag, limit: int = 1200) -> str:
    """Collect visible paragraphs/list items after a heading, stopping at any next heading."""
    parts: list[str] = []
    seen: set[str] = set()
    for node in heading.find_all_next(["h1", "h2", "h3", "h4", "h5", "h6", "p", "li"]):
        if node.name and node.name.startswith("h"):
            break
        text = clean_text(node.get_text(" ", strip=True))
        if text and text not in seen:
            parts.append(text)
            seen.add(text)
        if len(" ".join(parts)) >= limit:
            break
    return clean_text(" ".join(parts))[:limit]


def make_item(source_key: str, title: str, published: datetime, description: str) -> dict[str, str]:
    source = SOURCES[source_key]
    seed = f"{source_key}|{published.date().isoformat()}|{title}"
    guid = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]
    return {
        "guid": f"{source_key}-{guid}",
        "title": title,
        "link": source["url"],
        "published": published.isoformat(),
        "description": description or source["description"],
    }


def extract_claude_apps() -> list[dict[str, str]]:
    soup = fetch_soup(SOURCES["claude_apps"]["url"])
    entries: list[dict[str, str]] = []
    # The Intercom article uses h3 for the date and adjacent paragraph blocks
    # for title / body. Empty paragraph blocks separate individual updates.
    for date_heading in soup.find_all("h3"):
        published = parse_date(date_heading.get_text(" ", strip=True))
        if not published:
            continue
        title: str | None = None
        description: list[str] = []

        def flush() -> None:
            nonlocal title, description
            if title:
                entries.append(make_item("claude_apps", title, published, clean_text(" ".join(description))))
            title, description = None, []

        for sibling in date_heading.parent.find_next_siblings():
            if sibling.find(["h2", "h3"]):
                break
            text = clean_text(sibling.get_text(" ", strip=True))
            if not text:
                if description:
                    flush()
                continue
            if title is None:
                title = text
            else:
                description.append(text)
        flush()

    if not entries:
        for heading in soup.find_all(["h2", "h3"]):
            published = parse_date(heading.get_text(" ", strip=True))
            if published:
                description = text_until_next_heading(heading)
                if description:
                    entries.append(make_item("claude_apps", f"Claude update — {published:%B %-d, %Y}", published, description))
    return deduplicate(entries)


def extract_gemini_api() -> list[dict[str, str]]:
    soup = fetch_soup(SOURCES["gemini_api"]["url"])
    entries: list[dict[str, str]] = []
    for heading in soup.find_all(["h2", "h3", "h4"]):
        published = parse_date(heading.get_text(" ", strip=True))
        if not published:
            continue
        description = text_until_next_heading(heading)
        if description:
            title = f"Gemini API update — {published:%B %-d, %Y}"
            entries.append(make_item("gemini_api", title, published, description))
    return deduplicate(entries)


def deduplicate(entries: list[dict[str, str]]) -> list[dict[str, str]]:
    by_guid = {entry["guid"]: entry for entry in entries}
    return sorted(by_guid.values(), key=lambda item: item["published"], reverse=True)


def load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {"feeds": {}}
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))


def update_history(state: dict[str, Any], source_key: str, extracted: list[dict[str, str]]) -> list[dict[str, str]]:
    feeds = state.setdefault("feeds", {})
    old_items = feeds.get(source_key, {}).get("items", [])
    all_items = {item["guid"]: item for item in old_items}
    all_items.update({item["guid"]: item for item in extracted})
    items = sorted(all_items.values(), key=lambda item: item["published"], reverse=True)[:MAX_HISTORY]
    feeds[source_key] = {"items": items}
    return items


def write_rss(source_key: str, items: list[dict[str, str]]) -> None:
    source = SOURCES[source_key]
    FEED_DIR.mkdir(parents=True, exist_ok=True)
    rss = ET.Element("rss", version="2.0")
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = source["name"]
    ET.SubElement(channel, "link").text = source["url"]
    ET.SubElement(channel, "description").text = source["description"]
    ET.SubElement(channel, "language").text = "zh-CN"
    latest = max((datetime.fromisoformat(item["published"]) for item in items), default=utcnow())
    ET.SubElement(channel, "lastBuildDate").text = format_datetime(latest, usegmt=True)
    ET.SubElement(channel, "generator").text = "ai-release-notes-rss"

    for item in items:
        node = ET.SubElement(channel, "item")
        ET.SubElement(node, "title").text = item["title"]
        ET.SubElement(node, "link").text = item["link"]
        guid = ET.SubElement(node, "guid", isPermaLink="false")
        guid.text = item["guid"]
        published = datetime.fromisoformat(item["published"])
        ET.SubElement(node, "pubDate").text = format_datetime(published, usegmt=True)
        ET.SubElement(node, "description").text = item["description"]

    tree = ET.ElementTree(rss)
    ET.indent(tree, space="  ")
    output = FEED_DIR / source["feed_file"]
    tree.write(output, encoding="utf-8", xml_declaration=True)


def main() -> int:
    state = load_state()
    extractors = {"claude_apps": extract_claude_apps, "gemini_api": extract_gemini_api}
    successful = 0
    failures: list[str] = []

    for source_key, extractor in extractors.items():
        try:
            extracted = extractor()
            if not extracted:
                raise RuntimeError("No release-note entries were parsed")
            items = update_history(state, source_key, extracted)
            write_rss(source_key, items)
            print(f"{source_key}: {len(extracted)} parsed, {len(items)} retained")
            successful += 1
        except Exception as exc:
            failures.append(f"{source_key}: {exc}")
            existing = state.get("feeds", {}).get(source_key, {}).get("items", [])
            if existing:
                write_rss(source_key, existing)
                print(f"{source_key}: retained {len(existing)} old entries after parse failure")

    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if failures:
        print("\n".join(failures), file=sys.stderr)
    return 0 if successful else 1


if __name__ == "__main__":
    raise SystemExit(main())
