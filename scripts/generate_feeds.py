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
from urllib.parse import quote, urljoin
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
    "zhipu_news": {
        "name": "智谱官网新闻",
        "url": "https://www.zhipuai.cn/zh/news",
        "feed_file": "zhipu-news.xml",
        "description": "智谱官网新闻中的公司动态、产品发布与官方公告。",
    },
    "kimi_research": {
        "name": "Kimi 研究博客",
        "url": "https://www.kimi.ai/zh-hans/blog/",
        "feed_file": "kimi-research-blog.xml",
        "description": "Kimi 官方研究与技术博客文章。",
    },
    "deepseek_research_news": {
        "name": "DeepSeek 研究与动态",
        "url": "https://www.deepseek.com/news/",
        "feed_file": "deepseek-research-news.xml",
        "description": "DeepSeek 官网「研究与动态」中的产品动态，以及同页研究索引列出的论文与项目。",
    },
    "minimax_research": {
        "name": "MiniMax 研究博客",
        "url": "https://www.minimax.cn/blog",
        "feed_file": "minimax-research-blog.xml",
        "description": "MiniMax 中文官网研究博客中的技术文章与产品更新。",
    },
    "bytedance_seed": {
        "name": "字节跳动 Seed 官方动态",
        "url": "https://seed.bytedance.com/zh/",
        "feed_file": "bytedance-seed-updates.xml",
        "description": "字节跳动 Seed 官网公开的技术博客与官方动态。",
    },
    "sand_research": {
        "name": "Sand.ai 研究博客",
        "url": "https://sandai.cn/research/",
        "feed_file": "sand-research.xml",
        "description": "Sand.ai 中文官网研究页中的论文、模型发布与技术文章，包括 MAGI-2。",
    },
    "kling_blog": {
        "name": "Kling AI 官方博客",
        "url": "https://kling.ai/blog",
        "feed_file": "kling-blog.xml",
        "description": "Kling AI 官网博客文章与产品发布。",
    },
    "tongyi_wanxiang": {
        "name": "通义万相官网博客",
        "url": "https://tongyi.aliyun.com/wan/",
        "feed_file": "tongyi-wanxiang.xml",
        "description": "通义万相（万相）官网博客中的模型发布与研究说明。",
    },
    "runway_research": {
        "name": "Runway Research",
        "url": "https://runway.com/research",
        "feed_file": "runway-research.xml",
        "description": "Runway Research 官方 Publications 列表中的论文与研究发布。",
    },
    "heygen_research": {
        "name": "HeyGen Research",
        "url": "https://www.heygen.com/research",
        "feed_file": "heygen-research.xml",
        "description": "HeyGen Research 官方研究页中的技术文章与研究发布。",
    },
}

DATE_PATTERNS = (
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%Y.%m.%d",
    "%Y年%m月%d日",
    "%B %d, %Y",
    "%b %d, %Y",
    "%B %Y",
    "%b %Y",
)
SUMMARY_LIMIT = 500
ZH_LANGUAGE = "zh-CN,zh;q=0.9,en;q=0.8"


def utcnow() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("\xa0", " ")).strip()


def parse_date(value: str) -> datetime | None:
    value = clean_text(value)
    value = re.sub(r"(\d{1,2})(st|nd|rd|th)", r"\1", value, flags=re.I)
    value = re.sub(r"\s*([年月日])\s*", r"\1", value)
    for pattern in DATE_PATTERNS:
        try:
            parsed = datetime.strptime(value, pattern)
            if pattern in ("%B %Y", "%b %Y"):
                parsed = parsed.replace(day=1)
            return parsed.replace(tzinfo=UTC)
        except ValueError:
            pass
    return None


def decode_response(response: requests.Response) -> str:
    """Honor an explicit charset, and recover UTF-8 pages that omit one.

    requests otherwise falls back to ISO-8859-1, which corrupts pages such as
    DeepSeek's news listing.
    """
    if not response.encoding or response.encoding.lower() in {"iso-8859-1", "latin-1"}:
        response.encoding = response.apparent_encoding or "utf-8"
    return response.text


def fetch_soup(url: str, *, language: str = "en-US,en;q=0.9") -> BeautifulSoup:
    response = requests.get(
        url,
        headers={"User-Agent": USER_AGENT, "Accept-Language": language},
        timeout=40,
    )
    response.raise_for_status()
    return BeautifulSoup(decode_response(response), "html.parser")


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
    return decode_response(response)


def clip_summary(value: str, limit: int = SUMMARY_LIMIT) -> str:
    text = clean_text(value)
    if len(text) <= limit:
        return text
    clipped = text[:limit].rsplit(" ", 1)[0].rstrip("，,;；。")
    return f"{clipped}…"


def normalized_link(base: str, href: str) -> str:
    link = urljoin(base, href.strip())
    if link.startswith("http://"):
        link = "https://" + link[len("http://") :]
    return link


def link_slug(link: str) -> str:
    path = link.split("?", 1)[0].rstrip("/")
    slug = path.rsplit("/", 1)[-1]
    return slug or hashlib.sha256(link.encode("utf-8")).hexdigest()[:16]


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


def _gemini_markdown_entries(markdown: str) -> list[dict[str, str]]:
    """Parse the changelog markdown Google now embeds for non-JavaScript clients."""
    entries: list[dict[str, str]] = []
    published: datetime | None = None
    body: list[str] = []

    def flush() -> None:
        nonlocal published, body
        if published and body:
            description = clean_text(" ".join(body))
            description = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", description)
            description = re.sub(r"`([^`]+)`", r"\1", description)
            description = re.sub(r"\*\*([^*]+)\*\*", r"\1", description)
            description = description.replace("* ", "").strip()[:1200]
            if description:
                title = f"Gemini API update — {published:%B %-d, %Y}"
                entries.append(make_item("gemini_api", title, published, description))
        published, body = None, []

    for line in markdown.splitlines():
        heading = re.match(r"^##\s+(.+?)\s*$", line.strip())
        if heading:
            flush()
            heading_text = re.sub(r"\s*\{%.*?%\}\s*$", "", heading.group(1))
            published = parse_date(heading_text)
            continue
        if published and line.strip():
            body.append(line.strip())
    flush()
    return entries


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
    if not entries:
        noscript = soup.find("noscript")
        if noscript:
            entries.extend(_gemini_markdown_entries(noscript.get_text("\n", strip=False)))
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


def extract_zhipu_news() -> list[dict[str, str]]:
    """Read news cards from the public Chinese Zhipu news listing."""
    source = SOURCES["zhipu_news"]
    soup = fetch_soup(source["url"], language=ZH_LANGUAGE)
    entries: list[dict[str, str]] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        match = re.fullmatch(r"/zh/news/(\d+)", anchor["href"].split("?", 1)[0])
        if not match or match.group(1) in seen:
            continue
        title_node = anchor.find("h3")
        title = clean_text(title_node.get_text(" ", strip=True)) if title_node else ""
        published = next(
            (
                parsed
                for node in anchor.find_all("p")
                if (parsed := parse_date(node.get_text(" ", strip=True)))
            ),
            None,
        )
        if not title or not published:
            continue
        summary_node = anchor.find("span")
        summary = clean_text(summary_node.get_text(" ", strip=True)) if summary_node else ""
        news_id = match.group(1)
        entries.append(
            make_direct_item(
                "zhipu_news",
                news_id,
                title,
                published,
                clip_summary(summary),
                f"https://www.zhipuai.cn/zh/news/{news_id}",
            )
        )
        seen.add(news_id)
    return deduplicate(entries)


def _json_array_after(html: str, marker: str) -> list[Any]:
    """Decode a JSON array that follows a JavaScript-escaped marker."""
    start = html.find(marker)
    if start < 0:
        raise RuntimeError(f"Missing embedded data marker {marker!r}")
    index = start + len(marker)
    if index >= len(html) or html[index] != "[":
        raise RuntimeError(f"Embedded data after {marker!r} is not an array")
    depth = 0
    end = None
    for position in range(index, len(html)):
        char = html[position]
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                end = position + 1
                break
    if end is None:
        raise RuntimeError(f"Unterminated embedded array after {marker!r}")
    return json.loads(html[index:end].replace('\\"', '"'))


def extract_kimi_research() -> list[dict[str, str]]:
    """Read the article list embedded in Kimi's public Chinese research blog."""
    source = SOURCES["kimi_research"]
    response = requests.get(
        source["url"],
        headers={"User-Agent": USER_AGENT, "Accept-Language": ZH_LANGUAGE},
        timeout=40,
    )
    response.raise_for_status()
    html = decode_response(response)
    list_at = html.find('\\"articleList\\":')
    if list_at < 0:
        raise RuntimeError("Kimi research blog no longer exposes its public article list")
    articles = _json_array_after(html[list_at:], '\\"items\\":')
    entries: list[dict[str, str]] = []
    seen: set[str] = set()
    for article in articles:
        if not isinstance(article, dict) or "date" not in article:
            continue
        slug = str(article.get("href") or "").split("?", 1)[0].rstrip("/").rsplit("/", 1)[-1]
        title = clean_text(str(article.get("title") or ""))
        published = parse_date(str(article.get("date") or ""))
        if not slug or not title or not published or slug in seen:
            continue
        entries.append(
            make_direct_item(
                "kimi_research",
                quote(slug, safe="-._~"),
                title,
                published,
                clip_summary(str(article.get("description") or "")),
                f"https://www.kimi.ai/zh-hans/blog/{quote(slug, safe='-._~')}",
            )
        )
        seen.add(slug)
    return deduplicate(entries)


def extract_deepseek_research_news() -> list[dict[str, str]]:
    """Read product posts and the research index from DeepSeek's public news page."""
    source = SOURCES["deepseek_research_news"]
    soup = fetch_soup(source["url"], language=ZH_LANGUAGE)
    entries: list[dict[str, str]] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        path = anchor["href"].split("?", 1)[0]
        if not re.fullmatch(r"/news/[^/]+/?", path):
            continue
        heading = anchor.find(["h2", "h3"])
        title = clean_text(heading.get_text(" ", strip=True)) if heading else ""
        published = next(
            (
                parsed
                for node in anchor.find_all(["span", "p"])
                if (parsed := parse_date(node.get_text(" ", strip=True)))
            ),
            None,
        )
        if not title or not published:
            continue
        slug = path.strip("/").rsplit("/", 1)[-1]
        if slug in seen:
            continue
        summary = ""
        for paragraph in anchor.find_all("p"):
            text = clean_text(paragraph.get_text(" ", strip=True))
            if text and text != title and not parse_date(text) and not text.startswith("动态"):
                summary = text
                break
        entries.append(
            make_direct_item(
                "deepseek_research_news",
                slug,
                title,
                published,
                clip_summary(summary),
                normalized_link("https://www.deepseek.com", path if path.endswith("/") else f"{path}/"),
            )
        )
        seen.add(slug)

    for anchor in soup.select("a.ds-research-item"):
        link = normalized_link("https://www.deepseek.com", anchor.get("href") or "")
        title_node = anchor.find(class_="ds-research-title")
        date_node = anchor.find(class_="ds-research-date")
        title = clean_text(title_node.get_text(" ", strip=True)) if title_node else ""
        published = parse_date(date_node.get_text(" ", strip=True)) if date_node else None
        slug = link_slug(link)
        if not title or not published or not link.startswith("https://") or slug in seen:
            continue
        entries.append(
            make_direct_item(
                "deepseek_research_news",
                slug,
                title,
                published,
                "DeepSeek 官网研究索引列出的论文或项目。",
                link,
            )
        )
        seen.add(slug)
    return deduplicate(entries)


def extract_minimax_research() -> list[dict[str, str]]:
    """Read dated article cards from the public Chinese MiniMax research blog."""
    source = SOURCES["minimax_research"]
    soup = fetch_soup(source["url"], language=ZH_LANGUAGE)
    entries: list[dict[str, str]] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "").split("?", 1)[0]
        if not re.search(r"/blog/[^/]+$", href):
            continue
        title_node = anchor.find(["h2", "h3"])
        time_node = anchor.find("time")
        title = clean_text(title_node.get_text(" ", strip=True)) if title_node else ""
        published = parse_date(time_node.get_text(" ", strip=True)) if time_node else None
        slug = link_slug(href)
        if not title or not published or slug in seen:
            continue
        entries.append(
            make_direct_item(
                "minimax_research",
                quote(slug, safe="-._~%"),
                title,
                published,
                "",
                normalized_link("https://www.minimax.cn", href),
            )
        )
        seen.add(slug)
    return deduplicate(entries)


def extract_bytedance_seed() -> list[dict[str, str]]:
    """Read Seed's public article list, the same API used by its official blog pages."""
    source = SOURCES["bytedance_seed"]
    entries: list[dict[str, str]] = []
    seen: set[str] = set()
    page_token: Any = None
    for _ in range(8):
        params: dict[str, Any] = {"article_type": 2, "count": 20, "order_desc": 1}
        if page_token not in (None, ""):
            params["page_token"] = page_token
        response = requests.get(
            "https://seed.bytedance.com/api/get_article_list_v2",
            params=params,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json",
                "Accept-Language": ZH_LANGUAGE,
                "Referer": source["url"],
            },
            timeout=40,
        )
        response.raise_for_status()
        payload = response.json()
        articles = payload.get("sub_article_list")
        if not isinstance(articles, list):
            if entries and not payload.get("has_more"):
                break
            raise RuntimeError("Seed public article API returned an unexpected response")
        if not articles:
            break
        for article in articles:
            meta = article.get("ArticleMeta") or {}
            chinese = article.get("ArticleSubContentZh") or {}
            english = article.get("ArticleSubContentEn") or {}
            if meta.get("StatusZh") != 2:
                continue
            title = clean_text(str(chinese.get("Title") or ""))
            slug = clean_text(str(english.get("TitleKey") or chinese.get("TitleKey") or ""))
            published_raw = meta.get("PublishDate")
            article_id = str(meta.get("ArticleID") or "")
            if not title or not slug or not published_raw or not article_id or article_id in seen:
                continue
            timestamp = int(published_raw)
            if timestamp < 10_000_000_000:
                timestamp *= 1000
            published = datetime.fromtimestamp(timestamp / 1000, UTC)
            link = "https://seed.bytedance.com/zh/blog/" + quote(slug, safe="-._~")
            entries.append(
                make_direct_item(
                    "bytedance_seed",
                    article_id,
                    title,
                    published,
                    clip_summary(str(chinese.get("Abstract") or "")),
                    link,
                )
            )
            seen.add(article_id)
        if not payload.get("has_more"):
            break
        page_token = payload.get("next_page_token")
    return deduplicate(entries)


def extract_sand_research() -> list[dict[str, str]]:
    """Read research cards from Sand.ai's public Chinese research page."""
    source = SOURCES["sand_research"]
    soup = fetch_soup(source["url"], language=ZH_LANGUAGE)
    entries: list[dict[str, str]] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "")
        if not any(token in href for token in ("/blog/", "arxiv.org", "github.com")):
            continue
        title_node = anchor.find(["h2", "h3"]) or anchor.find(
            class_=lambda value: isinstance(value, str) and value.endswith("Title")
        )
        date_node = anchor.find(
            class_=lambda value: isinstance(value, str) and value.endswith("Date")
        )
        title = clean_text(title_node.get_text(" ", strip=True)) if title_node else ""
        date_text = clean_text(date_node.get_text(" ", strip=True)).split("·", 1)[0] if date_node else ""
        if not date_text:
            date_match = re.search(r"20\d{2}年\d{1,2}月\d{1,2}日", anchor.get_text(" ", strip=True))
            date_text = date_match.group(0) if date_match else ""
        published = parse_date(date_text)
        link = normalized_link(source["url"], href)
        slug = link_slug(link)
        if not title or not published or slug in seen:
            continue
        entries.append(
            make_direct_item(
                "sand_research",
                quote(slug, safe="-._~"),
                title,
                published,
                "",
                link,
            )
        )
        seen.add(slug)
    return deduplicate(entries)


def _kling_article_meta(url: str) -> tuple[datetime | None, str]:
    try:
        soup = fetch_soup(url)
    except requests.RequestException:
        return None, ""
    published = None
    meta = soup.find("meta", attrs={"property": "article:published_time"})
    if meta and meta.get("content"):
        try:
            published = datetime.fromisoformat(str(meta["content"]).replace("Z", "+00:00")).astimezone(UTC)
        except ValueError:
            published = None
    description = ""
    summary = soup.find("meta", attrs={"property": "og:description"})
    if summary and summary.get("content"):
        description = clip_summary(str(summary["content"]))
    return published, description


def extract_kling_blog() -> list[dict[str, str]]:
    """Read article cards from the public Kling AI blog listing."""
    source = SOURCES["kling_blog"]
    soup = fetch_soup(source["url"])
    entries: list[dict[str, str]] = []
    seen: set[str] = set()
    for anchor in soup.select("a.blog-card"):
        path = str(anchor.get("href") or "").split("?", 1)[0]
        if not re.fullmatch(r"/blog/[^/]+", path):
            continue
        title_node = anchor.find(class_="card-title")
        date_node = anchor.find(class_="card-meta")
        title = clean_text(title_node.get_text(" ", strip=True)) if title_node else ""
        published = parse_date(date_node.get_text(" ", strip=True)) if date_node else None
        slug = link_slug(path)
        if not title or not published or slug in seen:
            continue
        entries.append(
            make_direct_item(
                "kling_blog",
                quote(slug, safe="-._~"),
                title,
                published,
                "",
                f"https://kling.ai{path}",
            )
        )
        seen.add(slug)

    for anchor in soup.select("a.resource-link"):
        path = str(anchor.get("href") or "").split("?", 1)[0]
        slug = link_slug(path)
        title = clean_text(anchor.get_text(" ", strip=True))
        if not re.fullmatch(r"/blog/[^/]+", path) or not title or slug in seen:
            continue
        link = f"https://kling.ai{path}"
        published, description = _kling_article_meta(link)
        if not published:
            continue
        entries.append(
            make_direct_item(
                "kling_blog",
                quote(slug, safe="-._~"),
                title,
                published,
                description,
                link,
            )
        )
        seen.add(slug)
    return deduplicate(entries)


def _js_string_field(blob: str, name: str) -> str:
    match = re.search(rf'{re.escape(name)}:"((?:\\.|[^"\\])*)"', blob)
    if not match:
        return ""
    value = match.group(1)
    value = re.sub(r"\\u([0-9a-fA-F]{4})", lambda item: chr(int(item.group(1), 16)), value)
    return value.replace(r"\"", '"').replace(r"\n", " ").replace(r"\/", "/")


def extract_tongyi_wanxiang() -> list[dict[str, str]]:
    """Read Wan's official blog index shipped with the public Chinese site.

    https://tongyi.aliyun.com/wan/ is a client-rendered shell and does not list
    posts in the document. The site's own blog route loads a public article
    index; only title, date, and the one-line description are kept.
    """
    source = SOURCES["tongyi_wanxiang"]
    shell = fetch_soup(source["url"], language=ZH_LANGUAGE)
    html = str(shell)
    main_match = re.search(r"https://g\.alicdn\.com/tongyi-lab-fe/wan/[^\"']+/js/main\.js", html)
    if not main_match:
        raise RuntimeError("Tongyi Wanxiang page no longer points at its public blog bundle")
    main_js = fetch_text(main_match.group(0))
    chunk_match = re.search(
        r'articles/cn/blogArticles\.json":t\(\(\)=>tt\(\(\)=>import\("\./(blogArticles-[^"]+\.js)"\)',
        main_js,
    )
    if not chunk_match:
        raise RuntimeError("Tongyi Wanxiang no longer publishes its Chinese blog article index")
    chunk_url = main_match.group(0).rsplit("/", 1)[0] + "/" + chunk_match.group(1)
    bundle = fetch_text(chunk_url)
    entries: list[dict[str, str]] = []
    seen: set[str] = set()
    for match in re.finditer(r'\{id:"([^"]+)"', bundle):
        head = bundle[match.start() : match.start() + 4000].split(",content:", 1)[0]
        article_id = match.group(1)
        title = clean_text(_js_string_field(head, "title"))
        article_key = _js_string_field(head, "articleKey")
        published = parse_date(_js_string_field(head, "subTitle").split("·", 1)[0])
        if not title or not article_key or not published or article_id in seen:
            continue
        entries.append(
            make_direct_item(
                "tongyi_wanxiang",
                article_id,
                title,
                published,
                clip_summary(_js_string_field(head, "description")),
                "https://tongyi.aliyun.com/wan/blog/" + quote(article_key, safe="-._~"),
            )
        )
        seen.add(article_id)
    return deduplicate(entries)


def extract_runway_research() -> list[dict[str, str]]:
    """Read the dated publication rows linked from Runway's public research hub."""
    soup = fetch_soup("https://runway.com/research/publications")
    entries: list[dict[str, str]] = []
    seen: set[str] = set()
    for date_node in soup.find_all("div", class_=lambda value: value == "rw-bodycopy3"):
        date_text = clean_text(date_node.get_text(" ", strip=True))
        if len(date_text) > 32:
            continue
        published = parse_date(date_text)
        if not published:
            continue
        row = date_node
        title_node = None
        anchor = None
        summary_node = None
        for _ in range(4):
            row = row.parent
            if row is None:
                break
            title_node = row.find(class_=lambda value: value == "rw-h5")
            anchor = row.find("a", href=True)
            summary_node = row.find(class_=lambda value: value == "lg:w-7/16")
            heading_count = len(row.find_all(class_=lambda value: value == "rw-h5"))
            if title_node and anchor and heading_count == 1:
                break
        else:
            row = None
        if row is None or title_node is None or anchor is None:
            continue
        if len(row.find_all(class_=lambda value: value == "rw-h5")) != 1:
            continue
        title = clean_text(title_node.get_text(" ", strip=True)) if title_node else ""
        link = normalized_link("https://runway.com", str(anchor.get("href") or "")) if anchor else ""
        slug = link_slug(link)
        if not title or not link.startswith("https://") or slug in seen:
            continue
        summary = clean_text(summary_node.get_text(" ", strip=True)) if summary_node else ""
        entries.append(
            make_direct_item(
                "runway_research",
                quote(slug, safe="-._~"),
                title,
                published,
                clip_summary(summary),
                link,
            )
        )
        seen.add(slug)
    return deduplicate(entries)


def _next_flight_payloads(html: str) -> list[str]:
    """Decode Next.js flight chunks embedded in a server-rendered page."""
    payloads: list[str] = []
    for match in re.finditer(r'self\.__next_f\.push\(\[1,"((?:\\.|[^"\\])*)"\]\)', html):
        try:
            payloads.append(json.loads(f'"{match.group(1)}"'))
        except json.JSONDecodeError:
            continue
    return payloads


def _walk_objects(node: Any, found: list[dict[str, Any]]) -> None:
    if isinstance(node, dict):
        found.append(node)
        for value in node.values():
            _walk_objects(value, found)
    elif isinstance(node, list):
        for value in node:
            _walk_objects(value, found)


def _heygen_page_summary(url: str) -> str:
    """Use the article page's short meta description when the listing has none."""
    if not url.startswith("https://www.heygen.com/research/"):
        return ""
    try:
        soup = fetch_soup(url)
    except requests.RequestException:
        return ""
    meta = soup.find("meta", attrs={"property": "og:description"}) or soup.find(
        "meta", attrs={"name": "description"}
    )
    if not meta or not meta.get("content"):
        return ""
    return clip_summary(str(meta["content"]))


def extract_heygen_research() -> list[dict[str, str]]:
    """Read the article index embedded in HeyGen's public research listing.

    https://www.heygen.com/research has no RSS feed. The Next.js page already
    ships every research card, including items behind "Load more", with title,
    date, slug, and the short card description. Article bodies are not copied.
    """
    source = SOURCES["heygen_research"]
    response = requests.get(
        source["url"],
        headers={"User-Agent": USER_AGENT, "Accept": "text/html", "Accept-Language": "en-US,en;q=0.9"},
        timeout=40,
    )
    response.raise_for_status()
    html = decode_response(response)
    decoder = json.JSONDecoder()
    found: list[dict[str, Any]] = []
    for payload in _next_flight_payloads(html):
        index = 0
        while True:
            start = payload.find("{", index)
            if start < 0:
                break
            try:
                obj, end = decoder.raw_decode(payload[start:])
            except json.JSONDecodeError:
                index = start + 1
                continue
            _walk_objects(obj, found)
            index = start + end
    if not found:
        raise RuntimeError("HeyGen research page no longer exposes its public article index")

    best: dict[str, dict[str, Any]] = {}
    for article in found:
        slug = article.get("slug")
        title = article.get("title")
        published_raw = article.get("publishedDate")
        if not isinstance(slug, str) or not isinstance(title, str) or not isinstance(published_raw, str):
            continue
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,160}", slug):
            continue
        if not clean_text(title) or not parse_date(published_raw):
            continue
        current = best.get(slug)
        if current is None or (not current.get("description") and article.get("description")):
            best[slug] = article
    if not best:
        raise RuntimeError("HeyGen research page no longer exposes its public article index")

    entries: list[dict[str, str]] = []
    for slug, article in best.items():
        published = parse_date(str(article.get("publishedDate") or ""))
        assert published is not None
        external = article.get("externalUrl")
        if isinstance(external, str) and external.startswith("https://"):
            link = external
        else:
            link = "https://www.heygen.com/research/" + quote(slug, safe="-._~")
        description = article.get("description")
        summary = clip_summary(description) if isinstance(description, str) else ""
        if not summary:
            summary = _heygen_page_summary(link)
        entries.append(
            make_direct_item(
                "heygen_research",
                quote(slug, safe="-._~"),
                clean_text(str(article.get("title") or "")),
                published,
                summary,
                link,
            )
        )
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
        "zhipu_news": extract_zhipu_news,
        "kimi_research": extract_kimi_research,
        "deepseek_research_news": extract_deepseek_research_news,
        "minimax_research": extract_minimax_research,
        "bytedance_seed": extract_bytedance_seed,
        "sand_research": extract_sand_research,
        "kling_blog": extract_kling_blog,
        "tongyi_wanxiang": extract_tongyi_wanxiang,
        "runway_research": extract_runway_research,
        "heygen_research": extract_heygen_research,
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
