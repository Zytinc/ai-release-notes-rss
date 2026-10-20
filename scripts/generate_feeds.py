#!/usr/bin/env python3
"""Build stable RSS 2.0 feeds from public product release-note pages."""
from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import UTC, datetime
from email.utils import format_datetime, parsedate_to_datetime
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
ITUNES_NS = "http://www.itunes.com/dtds/podcast-1.0.dtd"
ET.register_namespace("itunes", ITUNES_NS)

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
    "xai_grok_bot": {
        "name": "Grok Bot Changelog",
        "url": "https://x.ai/changelog/bot",
        "fetch_url": "https://r.jina.ai/http://https://x.ai/changelog/bot/rss.xml",
        "feed_file": "xai-grok-bot-changelog.xml",
        "description": "Grok Bot 的公开版本更新、改进与修复说明。",
    },
    "manus_updates": {
        "name": "Manus Product Updates",
        "url": "https://manus.im/zh-cn/updates",
        "api_url": "https://api.manus.im/notifier.v1.NotificationPublicService/GetPublicUpdateNotifications",
        "feed_file": "manus-updates.xml",
        "description": "Manus 官方产品公告与功能更新。",
    },
    "manus_blog": {
        "name": "Manus Official Blog",
        "url": "https://manus.im/zh-cn/blog",
        "feed_file": "manus-blog.xml",
        "description": "Manus 官方博客文章，包括产品发布、客户案例与其他文章。",
    },
    "xiaoyuzhou_lemon_latte": {
        "name": "柠檬拿铁（小宇宙）",
        "url": "https://www.xiaoyuzhoufm.com/podcast/69d70d4093435f38037d6e0b",
        "feed_file": "xiaoyuzhou-lemon-latte.xml",
        "description": "小宇宙播客《柠檬拿铁》的单集更新与节目简介。",
        "author": "张小吉要多思考、JaredLiu",
        "image": "https://image.xyzcdn.net/FlktqFSAbDvPWzqF_P_o_6hXqPZx.jpg",
    },
}

DATE_PATTERNS = (
    "%Y年%m月%d日",
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


def fetch_text(url: str) -> str:
    response = requests.get(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/plain,text/markdown;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        },
        timeout=60,
    )
    response.raise_for_status()
    return response.text


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


def make_direct_item(
    source_key: str,
    guid: str,
    title: str,
    published: datetime,
    description: str,
    link: str,
) -> dict[str, str]:
    return {
        "guid": f"{source_key}-{guid}",
        "title": title,
        "link": link,
        "published": published.astimezone(UTC).isoformat(),
        "description": description or SOURCES[source_key]["description"],
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


XAI_ENTRY_HEADING = re.compile(
    r"^### \[(?P<title>.+)\]\((?P<link>https://x\.ai/changelog/bot#(?P<version>v[\w.-]+))\)$"
)
XAI_DATE = re.compile(r"^[A-Z][a-z]{2}, \d{2} [A-Z][a-z]{2} \d{4} \d{2}:\d{2}:\d{2} GMT$")


def clean_xai_markdown(lines: list[str]) -> str:
    """Keep update sections readable in RSS readers without relaying proxy metadata."""
    output: list[str] = []
    for line in lines:
        line = line.rstrip()
        if not line:
            continue
        if line.startswith("### "):
            output.append(line[4:] + ":")
        elif line.startswith("*   "):
            output.append("• " + line[4:])
        else:
            output.append(line)
    return "\n".join(output)


def extract_xai_grok_bot() -> list[dict[str, str]]:
    """Turn the publicly visible Grok Bot changelog into a stable local RSS mirror.

    xAI publishes an RSS file, but rejects ordinary server-side feed clients with HTTP 403.
    The proxy returns the same public changelog as Markdown, which is parsed into our own
    static feed for readers such as Folo.
    """
    source = SOURCES["xai_grok_bot"]
    raw = fetch_text(source["fetch_url"])
    marker = "Markdown Content:\n"
    if marker not in raw:
        raise RuntimeError("xAI changelog proxy response did not contain Markdown content")

    lines = raw.split(marker, 1)[1].splitlines()
    starts = [index for index, line in enumerate(lines) if XAI_ENTRY_HEADING.match(line.strip())]
    if not starts:
        raise RuntimeError("No Grok Bot changelog entries were parsed")

    entries: list[dict[str, str]] = []
    for position, start in enumerate(starts):
        heading = XAI_ENTRY_HEADING.match(lines[start].strip())
        assert heading is not None
        end = starts[position + 1] if position + 1 < len(starts) else len(lines)
        chunk = lines[start + 1 : end]

        source_link_index = next(
            (index for index, line in enumerate(chunk) if line.strip().startswith(f"[{heading['link']}](")),
            None,
        )
        if source_link_index is None:
            raise RuntimeError(f"Missing source link for {heading['version']}")
        pubdate = next((line.strip() for line in chunk[source_link_index + 1 :] if XAI_DATE.match(line.strip())), None)
        if not pubdate:
            raise RuntimeError(f"Missing publication date for {heading['version']}")

        published = parsedate_to_datetime(pubdate).astimezone(UTC)
        description = clean_xai_markdown(chunk[:source_link_index])
        entries.append(
            {
                "guid": f"xai_grok_bot-{heading['version']}",
                "title": heading["title"],
                "link": heading["link"],
                "published": published.isoformat(),
                "description": description or source["description"],
            }
        )
    return deduplicate(entries)


def extract_manus_updates() -> list[dict[str, str]]:
    """Read Manus's public update-notification API used by its official Updates page."""
    source = SOURCES["manus_updates"]
    response = requests.post(
        source["api_url"],
        json={"limit": 20},
        headers={
            "User-Agent": USER_AGENT,
            "Origin": "https://manus.im",
            "Referer": source["url"],
            "Accept": "application/json",
        },
        timeout=40,
    )
    response.raise_for_status()
    payload = response.json()
    if not payload.get("success") or not isinstance(payload.get("data"), list):
        raise RuntimeError("Manus public update API returned an unexpected response")

    entries: list[dict[str, str]] = []
    for notification in payload["data"]:
        if notification.get("notificationCategory") != "CATEGORY_UPDATE":
            continue
        if notification.get("isPopupUpdateLog") is False:
            continue
        detail = notification.get("detail") or {}
        title = clean_text(str(detail.get("title") or ""))
        created = notification.get("createAt")
        if not title or not created:
            continue
        published = datetime.fromisoformat(str(created).replace("Z", "+00:00"))
        button = detail.get("button") or {}
        target = button.get("target")
        link = target if isinstance(target, str) and target.startswith("https://") else source["url"]
        guid = str(notification.get("uid") or hashlib.sha256(f"{created}|{title}".encode()).hexdigest()[:24])
        entries.append(
            make_direct_item(
                "manus_updates",
                guid,
                title,
                published,
                clean_text(str(detail.get("content") or "")),
                link,
            )
        )
    return deduplicate(entries)


def extract_manus_blog() -> list[dict[str, str]]:
    """Read article cards from the public Chinese Manus Blog listing."""
    source = SOURCES["manus_blog"]
    soup = fetch_soup(source["url"])
    entries: list[dict[str, str]] = []
    seen_slugs: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        path = anchor["href"].split("?", 1)[0].rstrip("/")
        match = re.fullmatch(r"/(?:[a-z]{2}(?:-[a-z]{2})?/)?blog/([^/]+)", path, flags=re.I)
        if not match:
            continue
        slug = match.group(1)
        if slug in seen_slugs:
            continue
        link = f"https://manus.im/zh-cn/blog/{slug}"
        detail_description = ""
        title_node = anchor.find(["h2", "h3"])
        title = clean_text(title_node.get_text(" ", strip=True)) if title_node else ""
        if not title and title_node:
            title = clean_text(str(title_node.get("title") or ""))
        if not title:
            title = clean_text(str(anchor.get("title") or ""))
        if not title:
            article_soup = fetch_soup(link)
            article_title = article_soup.find("h1")
            title = clean_text(article_title.get_text(" ", strip=True)) if article_title else ""
            description_meta = article_soup.find("meta", attrs={"property": "og:description"})
            if description_meta:
                detail_description = clean_text(str(description_meta.get("content") or ""))
        if not title:
            title = slug.replace("-", " ").replace("_", " ").strip().capitalize()

        date_text = next(
            (
                clean_text(span.get_text(" ", strip=True))
                for span in anchor.find_all("span")
                if re.search(r"\d{4}年\d{1,2}月\d{1,2}日|[A-Z][a-z]+ \d{1,2}, \d{4}", span.get_text(" ", strip=True))
            ),
            "",
        )
        published = parse_date(date_text)
        if not published:
            continue
        description_node = anchor.find("p")
        description = clean_text(description_node.get_text(" ", strip=True)) if description_node else ""
        category = next(
            (
                clean_text(span.get_text(" ", strip=True))
                for span in anchor.find_all("span")
                if clean_text(span.get_text(" ", strip=True)) not in {"·", date_text}
            ),
            "",
        )
        if not description and detail_description:
            description = detail_description
        if not description and category:
            description = f"Manus 官方博客文章（{category}）。"
        entries.append(make_direct_item("manus_blog", slug, title, published, description, link))
        seen_slugs.add(slug)
    return deduplicate(entries)


def extract_xiaoyuzhou_lemon_latte() -> list[dict[str, str]]:
    """Build a podcast feed from public episode metadata embedded in Xiaoyuzhou's page."""
    source = SOURCES["xiaoyuzhou_lemon_latte"]
    response = requests.get(
        source["url"],
        headers={
            "User-Agent": USER_AGENT,
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        },
        timeout=40,
    )
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    next_data = soup.find("script", id="__NEXT_DATA__")
    if not next_data:
        raise RuntimeError("Xiaoyuzhou podcast page no longer exposes its public episode data")
    payload = json.loads(next_data.string or next_data.get_text())
    podcast = payload.get("props", {}).get("pageProps", {}).get("podcast")
    if not isinstance(podcast, dict) or podcast.get("pid") != "69d70d4093435f38037d6e0b":
        raise RuntimeError("Unexpected Xiaoyuzhou podcast page data")

    entries: list[dict[str, str]] = []
    for episode in podcast.get("episodes", []):
        if episode.get("status") not in (None, "NORMAL"):
            continue
        if episode.get("isPrivateMedia") or episode.get("payType") not in (None, "FREE"):
            continue
        title = clean_text(str(episode.get("title") or ""))
        published_raw = episode.get("pubDate")
        episode_id = str(episode.get("eid") or "")
        if not title or not published_raw or not episode_id:
            continue
        published = datetime.fromisoformat(str(published_raw).replace("Z", "+00:00"))
        description = str(episode.get("description") or episode.get("shownotes") or "")
        description = "\n".join(line.rstrip() for line in description.replace("\r\n", "\n").splitlines()).strip()
        item = make_direct_item(
            "xiaoyuzhou_lemon_latte",
            episode_id,
            title,
            published,
            description,
            f"https://www.xiaoyuzhoufm.com/episode/{episode_id}",
        )
        enclosure = episode.get("enclosure") or {}
        media = episode.get("media") or {}
        media_url = enclosure.get("url") or (media.get("source") or {}).get("url")
        if media_url:
            item["enclosure_url"] = str(media_url)
            item["enclosure_length"] = str(media.get("size") or enclosure.get("length") or 0)
            item["enclosure_type"] = str(media.get("mimeType") or "audio/mp4")
        duration = episode.get("duration")
        if duration:
            seconds = int(float(duration))
            hours, remainder = divmod(seconds, 3600)
            minutes, seconds = divmod(remainder, 60)
            item["duration"] = f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes}:{seconds:02d}"
        entries.append(item)
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
    if source.get("author"):
        ET.SubElement(channel, f"{{{ITUNES_NS}}}author").text = source["author"]
        ET.SubElement(channel, f"{{{ITUNES_NS}}}summary").text = source["description"]
        ET.SubElement(channel, f"{{{ITUNES_NS}}}explicit").text = "false"
    if source.get("image"):
        ET.SubElement(channel, "image").extend([
            ET.Element("url"),
            ET.Element("title"),
            ET.Element("link"),
        ])
        image_node = channel.find("image")
        assert image_node is not None
        image_node.find("url").text = source["image"]
        image_node.find("title").text = source["name"]
        image_node.find("link").text = source["url"]
        ET.SubElement(channel, f"{{{ITUNES_NS}}}image", href=source["image"])
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
        if item.get("enclosure_url"):
            ET.SubElement(
                node,
                "enclosure",
                url=item["enclosure_url"],
                length=item.get("enclosure_length", "0"),
                type=item.get("enclosure_type", "audio/mp4"),
            )
        if item.get("duration"):
            ET.SubElement(node, f"{{{ITUNES_NS}}}duration").text = item["duration"]

    tree = ET.ElementTree(rss)
    ET.indent(tree, space="  ")
    output = FEED_DIR / source["feed_file"]
    tree.write(output, encoding="utf-8", xml_declaration=True)


def main() -> int:
    state = load_state()
    extractors = {
        "claude_apps": extract_claude_apps,
        "gemini_api": extract_gemini_api,
        "xai_grok_bot": extract_xai_grok_bot,
        "manus_updates": extract_manus_updates,
        "manus_blog": extract_manus_blog,
        "xiaoyuzhou_lemon_latte": extract_xiaoyuzhou_lemon_latte,
    }
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
