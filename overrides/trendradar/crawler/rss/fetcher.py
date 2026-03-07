# coding=utf-8
"""
RSS 抓取器（稳定性增强版）

增强点：
1) 主源 RSSHub 失败时自动回退 Nitter RSS
2) 回退失败后再读取本地 SQLite 历史缓存（避免全空）
3) requests 会话增加重试策略，降低瞬时 5xx/网络抖动影响
"""

import random
import re
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .parser import RSSParser
from trendradar.storage.base import RSSData, RSSItem
from trendradar.utils.time import (
    DEFAULT_TIMEZONE,
    get_configured_time,
    is_within_days,
)


@dataclass
class RSSFeedConfig:
    """RSS 源配置"""

    id: str
    name: str
    url: str
    max_items: int = 0
    enabled: bool = True
    max_age_days: Optional[int] = None


class RSSFetcher:
    """RSS 抓取器（稳定性增强版）"""

    USERNAME_PATTERN = re.compile(r"/twitter/user/([A-Za-z0-9_]+)")

    def __init__(
        self,
        feeds: List[RSSFeedConfig],
        request_interval: int = 2000,
        timeout: int = 15,
        use_proxy: bool = False,
        proxy_url: str = "",
        timezone: str = DEFAULT_TIMEZONE,
        freshness_enabled: bool = True,
        default_max_age_days: int = 3,
    ):
        self.feeds = [f for f in feeds if f.enabled]
        self.request_interval = request_interval
        self.timeout = timeout
        self.use_proxy = use_proxy
        self.proxy_url = proxy_url
        self.timezone = timezone
        self.freshness_enabled = freshness_enabled
        self.default_max_age_days = default_max_age_days

        self.parser = RSSParser()
        self.session = self._create_session()

    def _create_session(self) -> requests.Session:
        session = requests.Session()
        session.headers.update(
            {
                "User-Agent": "TrendRadar/2.0 RSS Reader (https://github.com/trendradar)",
                "Accept": "application/feed+json, application/json, application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            }
        )

        # 针对临时 429/5xx 的轻量重试
        retry = Retry(
            total=2,
            connect=2,
            read=2,
            backoff_factor=0.4,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("http://", adapter)
        session.mount("https://", adapter)

        if self.use_proxy and self.proxy_url:
            session.proxies = {"http": self.proxy_url, "https": self.proxy_url}

        return session

    def _filter_by_freshness(
        self,
        items: List[RSSItem],
        feed: RSSFeedConfig,
    ) -> Tuple[List[RSSItem], int]:
        if not self.freshness_enabled:
            return items, 0

        max_days = feed.max_age_days
        if max_days is None:
            max_days = self.default_max_age_days
        if max_days == 0:
            return items, 0

        filtered: List[RSSItem] = []
        for item in items:
            if not item.published_at:
                filtered.append(item)
            elif is_within_days(item.published_at, max_days, self.timezone):
                filtered.append(item)

        return filtered, len(items) - len(filtered)

    def _parse_username_from_feed_url(self, url: str) -> str:
        m = self.USERNAME_PATTERN.search(url or "")
        if not m:
            return ""
        return m.group(1).strip()

    def _build_items_from_response_text(
        self,
        *,
        feed: RSSFeedConfig,
        response_text: str,
        source_name: str,
        source_url: str,
    ) -> List[RSSItem]:
        parsed_items = self.parser.parse(response_text, source_url)
        if feed.max_items > 0:
            parsed_items = parsed_items[: feed.max_items]

        now = get_configured_time(self.timezone)
        crawl_time = now.strftime("%H:%M")
        items: List[RSSItem] = []
        for parsed in parsed_items:
            items.append(
                RSSItem(
                    title=parsed.title,
                    feed_id=feed.id,
                    feed_name=feed.name,
                    url=parsed.url,
                    published_at=parsed.published_at or "",
                    summary=parsed.summary or "",
                    author=parsed.author or "",
                    crawl_time=crawl_time,
                    first_time=crawl_time,
                    last_time=crawl_time,
                    count=1,
                )
            )
        print(f"[RSS] {feed.name}: 获取 {len(items)} 条 (source={source_name})")
        return items

    def _fetch_text(self, url: str, timeout: int) -> str:
        resp = self.session.get(url, timeout=timeout)
        resp.raise_for_status()
        return resp.text

    def _fallback_nitter(self, feed: RSSFeedConfig, username: str) -> Tuple[List[RSSItem], Optional[str]]:
        if not username:
            return [], "无法解析用户名，跳过 Nitter 回退"
        nitter_url = f"https://nitter.net/{quote(username)}/rss"
        try:
            text = self._fetch_text(nitter_url, timeout=min(20, self.timeout + 3))
            items = self._build_items_from_response_text(
                feed=feed,
                response_text=text,
                source_name="nitter",
                source_url=nitter_url,
            )
            return items, None
        except Exception as exc:
            return [], f"Nitter 回退失败: {exc}"

    def _latest_local_rss_db(self) -> Optional[Path]:
        output_rss_dir = Path("/app/output/rss")
        if not output_rss_dir.exists():
            return None
        dbs = sorted(output_rss_dir.glob("*.db"))
        if not dbs:
            return None
        return dbs[-1]

    def _fallback_sqlite(self, feed: RSSFeedConfig) -> Tuple[List[RSSItem], Optional[str]]:
        db_path = self._latest_local_rss_db()
        if not db_path:
            return [], "本地缓存库不存在"
        try:
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT title, url, published_at, summary, author
                FROM rss_items
                WHERE feed_id = ?
                ORDER BY datetime(published_at) DESC, id DESC
                LIMIT 5
                """,
                (feed.id,),
            ).fetchall()
            conn.close()
        except Exception as exc:
            return [], f"读取本地缓存失败: {exc}"

        if not rows:
            return [], "本地缓存无该源历史条目"

        now = get_configured_time(self.timezone)
        crawl_time = now.strftime("%H:%M")
        items: List[RSSItem] = []
        for row in rows:
            items.append(
                RSSItem(
                    title=str(row["title"] or "").strip(),
                    feed_id=feed.id,
                    feed_name=feed.name,
                    url=str(row["url"] or "").strip(),
                    published_at=str(row["published_at"] or "").strip(),
                    summary=str(row["summary"] or "").strip(),
                    author=str(row["author"] or "").strip(),
                    crawl_time=crawl_time,
                    first_time=crawl_time,
                    last_time=crawl_time,
                    count=1,
                )
            )

        print(f"[RSS] {feed.name}: 使用本地缓存回退 {len(items)} 条 (db={db_path.name})")
        return items, None

    def fetch_feed(self, feed: RSSFeedConfig) -> Tuple[List[RSSItem], Optional[str]]:
        username = self._parse_username_from_feed_url(feed.url)

        try:
            text = self._fetch_text(feed.url, timeout=self.timeout)
            items = self._build_items_from_response_text(
                feed=feed,
                response_text=text,
                source_name="rsshub",
                source_url=feed.url,
            )
            return items, None
        except requests.Timeout:
            primary_error = f"请求超时 ({self.timeout}s)"
        except requests.RequestException as exc:
            primary_error = f"请求失败: {exc}"
        except ValueError as exc:
            primary_error = f"解析失败: {exc}"
        except Exception as exc:
            primary_error = f"未知错误: {exc}"

        print(f"[RSS] {feed.name}: 主源失败 -> {primary_error}")

        fallback_items, fallback_error = self._fallback_nitter(feed, username=username)
        if fallback_items:
            print(f"[RSS] {feed.name}: 已回退至 Nitter")
            return fallback_items, None
        if fallback_error:
            print(f"[RSS] {feed.name}: {fallback_error}")

        sqlite_items, sqlite_error = self._fallback_sqlite(feed)
        if sqlite_items:
            print(f"[RSS] {feed.name}: 已回退至本地 SQLite 缓存")
            return sqlite_items, None

        error = f"{primary_error}; {fallback_error or ''}; {sqlite_error or ''}".strip("; ")
        print(f"[RSS] {feed.name}: 全部回退失败 -> {error}")
        return [], error

    def fetch_all(self) -> RSSData:
        all_items: Dict[str, List[RSSItem]] = {}
        id_to_name: Dict[str, str] = {}
        failed_ids: List[str] = []

        now = get_configured_time(self.timezone)
        crawl_time = now.strftime("%H:%M")
        crawl_date = now.strftime("%Y-%m-%d")

        print(f"[RSS] 开始抓取 {len(self.feeds)} 个 RSS 源...")
        for i, feed in enumerate(self.feeds):
            if i > 0:
                interval = self.request_interval / 1000
                jitter = random.uniform(-0.2, 0.2) * interval
                time.sleep(max(0.0, interval + jitter))

            items, error = self.fetch_feed(feed)
            id_to_name[feed.id] = feed.name

            if error:
                failed_ids.append(feed.id)
            else:
                all_items[feed.id] = items

        total_items = sum(len(items) for items in all_items.values())
        print(
            f"[RSS] 抓取完成: {len(all_items)} 个源成功, {len(failed_ids)} 个失败, 共 {total_items} 条"
        )

        return RSSData(
            date=crawl_date,
            crawl_time=crawl_time,
            items=all_items,
            id_to_name=id_to_name,
            failed_ids=failed_ids,
        )

    @classmethod
    def from_config(cls, config: Dict) -> "RSSFetcher":
        freshness_config = config.get("freshness_filter", {})
        freshness_enabled = freshness_config.get("enabled", True)
        default_max_age_days = freshness_config.get("max_age_days", 3)

        feeds: List[RSSFeedConfig] = []
        for feed_config in config.get("feeds", []):
            max_age_days_raw = feed_config.get("max_age_days")
            max_age_days = None
            if max_age_days_raw is not None:
                try:
                    max_age_days = int(max_age_days_raw)
                    if max_age_days < 0:
                        feed_id = feed_config.get("id", "unknown")
                        print(f"[警告] RSS feed '{feed_id}' 的 max_age_days 为负数，将使用全局默认值")
                        max_age_days = None
                except (ValueError, TypeError):
                    feed_id = feed_config.get("id", "unknown")
                    print(f"[警告] RSS feed '{feed_id}' 的 max_age_days 格式错误：{max_age_days_raw}")
                    max_age_days = None

            feed = RSSFeedConfig(
                id=feed_config.get("id", ""),
                name=feed_config.get("name", ""),
                url=feed_config.get("url", ""),
                max_items=feed_config.get("max_items", 0),
                enabled=feed_config.get("enabled", True),
                max_age_days=max_age_days,
            )
            if feed.id and feed.url:
                feeds.append(feed)

        return cls(
            feeds=feeds,
            request_interval=config.get("request_interval", 2000),
            timeout=config.get("timeout", 15),
            use_proxy=config.get("use_proxy", False),
            proxy_url=config.get("proxy_url", ""),
            timezone=config.get("timezone", DEFAULT_TIMEZONE),
            freshness_enabled=freshness_enabled,
            default_max_age_days=default_max_age_days,
        )

