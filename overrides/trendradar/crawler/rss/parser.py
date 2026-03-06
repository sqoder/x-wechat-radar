# coding=utf-8
"""
RSS 解析器

支持 RSS 2.0、Atom 和 JSON Feed 1.1 格式的解析
"""

import re
import html
import json
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Dict, Any
from email.utils import parsedate_to_datetime

try:
    import feedparser
    HAS_FEEDPARSER = True
except ImportError:
    HAS_FEEDPARSER = False
    feedparser = None


@dataclass
class ParsedRSSItem:
    """解析后的 RSS 条目"""
    title: str
    url: str
    published_at: Optional[str] = None
    summary: Optional[str] = None
    author: Optional[str] = None
    guid: Optional[str] = None


class RSSParser:
    """RSS 解析器"""

    def __init__(self, max_summary_length: int = 500):
        """
        初始化解析器

        Args:
            max_summary_length: 摘要最大长度
        """
        if not HAS_FEEDPARSER:
            raise ImportError("RSS 解析需要安装 feedparser: pip install feedparser")

        self.max_summary_length = max_summary_length

    def parse(self, content: str, feed_url: str = "") -> List[ParsedRSSItem]:
        """
        解析 RSS/Atom/JSON Feed 内容

        Args:
            content: Feed 内容（XML 或 JSON）
            feed_url: Feed URL（用于错误提示）

        Returns:
            解析后的条目列表
        """
        # 先尝试检测 JSON Feed
        if self._is_json_feed(content):
            return self._parse_json_feed(content, feed_url)

        # 使用 feedparser 解析 RSS/Atom
        feed = feedparser.parse(content)

        if feed.bozo and not feed.entries:
            raise ValueError(f"RSS 解析失败 ({feed_url}): {feed.bozo_exception}")

        items = []
        for entry in feed.entries:
            item = self._parse_entry(entry)
            if item:
                items.append(item)

        return items

    def _is_json_feed(self, content: str) -> bool:
        """
        检测内容是否为 JSON Feed 格式

        JSON Feed 必须包含 version 字段，值为 https://jsonfeed.org/version/1 或 1.1
        """
        content = content.strip()
        if not content.startswith("{"):
            return False

        try:
            data = json.loads(content)
            version = data.get("version", "")
            return "jsonfeed.org" in version
        except (json.JSONDecodeError, TypeError):
            return False

    def _parse_json_feed(self, content: str, feed_url: str = "") -> List[ParsedRSSItem]:
        """
        解析 JSON Feed 1.1 格式

        JSON Feed 规范: https://www.jsonfeed.org/version/1.1/

        Args:
            content: JSON Feed 内容
            feed_url: Feed URL（用于错误提示）

        Returns:
            解析后的条目列表
        """
        try:
            data = json.loads(content)
        except json.JSONDecodeError as e:
            raise ValueError(f"JSON Feed 解析失败 ({feed_url}): {e}")

        items_data = data.get("items", [])
        if not items_data:
            return []

        items = []
        for item_data in items_data:
            item = self._parse_json_feed_item(item_data)
            if item:
                items.append(item)

        return items

    def _parse_json_feed_item(self, item_data: Dict[str, Any]) -> Optional[ParsedRSSItem]:
        """解析单个 JSON Feed 条目"""
        raw_title = self._clean_text(item_data.get("title", ""))
        content_text = item_data.get("content_text", "")
        content_html = item_data.get("content_html", "")
        raw_summary = item_data.get("summary", "")

        body_text = self._clean_text(raw_summary or content_text or content_html)
        media_urls = self._extract_media_urls(content_html or raw_summary)
        hashtags = self._extract_hashtags(f"{raw_title} {body_text}")
        summary = self._compose_summary(body_text, hashtags, media_urls)

        title = raw_title
        if not title:
            title = self._build_fallback_title(body_text, media_urls)

        # URL
        url = item_data.get("url", "") or item_data.get("external_url", "")

        # 发布时间（ISO 8601 格式）
        published_at = None
        date_str = item_data.get("date_published") or item_data.get("date_modified")
        if date_str:
            published_at = self._parse_iso_date(date_str)

        # 作者
        author = None
        authors = item_data.get("authors", [])
        if authors:
            names = [a.get("name", "") for a in authors if isinstance(a, dict) and a.get("name")]
            if names:
                author = ", ".join(names)

        # GUID
        guid = item_data.get("id", "") or url

        return ParsedRSSItem(
            title=title,
            url=url,
            published_at=published_at,
            summary=summary or None,
            author=author,
            guid=guid,
        )

    def _parse_iso_date(self, date_str: str) -> Optional[str]:
        """解析 ISO 8601 日期格式"""
        if not date_str:
            return None

        try:
            # 处理常见的 ISO 8601 格式
            # 替换 Z 为 +00:00
            date_str = date_str.replace("Z", "+00:00")
            dt = datetime.fromisoformat(date_str)
            return dt.isoformat()
        except (ValueError, TypeError):
            pass

        return None

    def parse_url(self, url: str, timeout: int = 10) -> List[ParsedRSSItem]:
        """
        从 URL 解析 RSS

        Args:
            url: RSS URL
            timeout: 超时时间（秒）

        Returns:
            解析后的条目列表
        """
        import requests

        response = requests.get(url, timeout=timeout, headers={
            "User-Agent": "TrendRadar/2.0 RSS Reader"
        })
        response.raise_for_status()

        return self.parse(response.text, url)

    def _parse_entry(self, entry: Any) -> Optional[ParsedRSSItem]:
        """解析单个条目"""
        title = self._clean_text(entry.get("title", ""))
        raw_summary = self._extract_raw_summary(entry)
        media_urls = self._extract_media_urls(raw_summary)
        summary = self._parse_summary(entry, title)
        if not title:
            title = self._build_fallback_title(self._clean_text(raw_summary), media_urls)

        url = entry.get("link", "")
        if not url:
            # 尝试从 links 中获取
            links = entry.get("links", [])
            for link in links:
                if link.get("rel") == "alternate" or link.get("type", "").startswith("text/html"):
                    url = link.get("href", "")
                    break
            if not url and links:
                url = links[0].get("href", "")

        published_at = self._parse_date(entry)
        author = self._parse_author(entry)
        guid = entry.get("id") or entry.get("guid", {}).get("value") or url

        return ParsedRSSItem(
            title=title,
            url=url,
            published_at=published_at,
            summary=summary,
            author=author,
            guid=guid,
        )

    def _clean_text(self, text: str) -> str:
        """清理文本"""
        if not text:
            return ""

        # 解码 HTML 实体
        text = html.unescape(text)

        # 移除 HTML 标签
        text = re.sub(r'<[^>]+>', '', text)

        # 移除多余空白
        text = re.sub(r'\s+', ' ', text)

        return text.strip()

    def _extract_raw_summary(self, entry: Any) -> str:
        """提取原始摘要 HTML"""
        raw_summary = entry.get("summary") or entry.get("description", "")
        if not raw_summary:
            content = entry.get("content", [])
            if content and isinstance(content, list):
                raw_summary = content[0].get("value", "")
        return raw_summary or ""

    def _extract_media_urls(self, raw_html: str) -> Dict[str, List[str]]:
        """从原始 HTML 中提取媒体 URL"""
        if not raw_html:
            return {"video": [], "image": []}

        video_urls = re.findall(r'<video[^>]+src=["\']([^"\']+)["\']', raw_html, flags=re.IGNORECASE)
        image_urls = re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', raw_html, flags=re.IGNORECASE)

        def dedupe(values: List[str]) -> List[str]:
            result = []
            seen = set()
            for value in values:
                if value and value not in seen:
                    result.append(value)
                    seen.add(value)
            return result

        return {
            "video": dedupe(video_urls),
            "image": dedupe(image_urls),
        }

    def _extract_hashtags(self, text: str) -> List[str]:
        """提取 #标签"""
        if not text:
            return []
        tags = re.findall(r'(?<!\w)#([A-Za-z0-9_]{1,64})', text)
        result = []
        seen = set()
        for tag in tags:
            full_tag = f"#{tag}"
            if full_tag not in seen:
                result.append(full_tag)
                seen.add(full_tag)
        return result

    def _compose_summary(
        self,
        body_text: str,
        hashtags: List[str],
        media_urls: Dict[str, List[str]],
    ) -> Optional[str]:
        """组装可读摘要，包含正文、标签、媒体链接"""
        parts: List[str] = []
        if hashtags:
            parts.append(f"标签: {' '.join(hashtags[:8])}")
        if media_urls.get("video"):
            parts.append(f"视频: {media_urls['video'][0]}")
        if media_urls.get("image"):
            parts.append(f"图片: {media_urls['image'][0]}")
        if body_text:
            parts.append(f"内容: {body_text}")

        if not parts:
            return None

        summary = " | ".join(parts)
        if len(summary) > self.max_summary_length:
            summary = summary[:self.max_summary_length] + "..."
        return summary

    def _build_fallback_title(self, fallback_text: Optional[str], media_urls: Dict[str, List[str]]) -> str:
        """为无标题条目构造兜底标题，确保视频帖不会被过滤掉"""
        if fallback_text:
            cleaned = self._clean_text(fallback_text)
            if cleaned:
                if len(cleaned) > 100:
                    return cleaned[:100] + "..."
                return cleaned

        if media_urls.get("video"):
            return "[视频帖]"
        if media_urls.get("image"):
            return "[图片帖]"
        return "[无文本帖子]"

    def _parse_date(self, entry: Any) -> Optional[str]:
        """解析发布日期"""
        # feedparser 会自动解析日期到 published_parsed
        date_struct = entry.get("published_parsed") or entry.get("updated_parsed")

        if date_struct:
            try:
                dt = datetime(*date_struct[:6])
                return dt.isoformat()
            except (ValueError, TypeError):
                pass

        # 尝试手动解析
        date_str = entry.get("published") or entry.get("updated")
        if date_str:
            try:
                dt = parsedate_to_datetime(date_str)
                return dt.isoformat()
            except (ValueError, TypeError):
                pass

            # 尝试 ISO 格式
            try:
                dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                return dt.isoformat()
            except (ValueError, TypeError):
                pass

        return None

    def _parse_summary(self, entry: Any, title_hint: str = "") -> Optional[str]:
        """解析摘要"""
        raw_summary = self._extract_raw_summary(entry)
        if not raw_summary:
            return None

        body_text = self._clean_text(raw_summary)
        media_urls = self._extract_media_urls(raw_summary)
        hashtags = self._extract_hashtags(f"{title_hint} {body_text}")
        return self._compose_summary(body_text, hashtags, media_urls)

    def _parse_author(self, entry: Any) -> Optional[str]:
        """解析作者"""
        author = entry.get("author")
        if author:
            return self._clean_text(author)

        # 尝试从 dc:creator 获取
        author = entry.get("dc_creator")
        if author:
            return self._clean_text(author)

        # 尝试从 authors 列表获取
        authors = entry.get("authors", [])
        if authors:
            names = [a.get("name", "") for a in authors if a.get("name")]
            if names:
                return ", ".join(names)

        return None
