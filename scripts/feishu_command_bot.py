#!/usr/bin/env python3
# coding: utf-8
"""
飞书指令机器人（长连接模式，0 元本地可跑）。

能力：
- 在飞书群里发“查 elonmusk 最新帖子”后，机器人自动回复
- 自动回退数据源：RSSHub -> Nitter RSS -> 本地 SQLite 历史库
- 可选本地翻译/总结（Ollama）
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sqlite3
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Deque, Dict, List, Optional, Set, Tuple
from zoneinfo import ZoneInfo

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from feishu_app_support import (  # noqa: E402
    list_active_recipients,
    parse_bool,
    resolve_data_path,
    resolve_recipients_file,
    send_text_message,
    send_text_to_recipients,
    upsert_p2p_recipient,
)
from x_latest_post import (  # noqa: E402
    ENV_PATH,
    PostItem,
    build_post_message_text,
    fetch_from_local_sqlite,
    fetch_from_nitter,
    fetch_from_rsshub,
    format_china_time,
    has_meaningful_text,
    load_env_file,
    maybe_zh_translate,
    normalize_ai_base,
    resolve_rss_db_path,
    strip_openai_prefix,
    summarize_cn,
    tags_cn,
)


HELP_TEXT = (
    "我支持这些命令：\n"
    "1) 查 elonmusk 最新帖子\n"
    "2) 查看 @realDonaldTrump 最新推特\n"
    "3) 我要看马斯克最新帖子\n"
)
CN_TIMEZONE = ZoneInfo("Asia/Shanghai")

MAX_SEEN_MESSAGE_IDS = 2000
SEEN_MESSAGE_IDS: Set[str] = set()
SEEN_MESSAGE_QUEUE: Deque[str] = deque(maxlen=MAX_SEEN_MESSAGE_IDS)


ALIAS_MAP = {
    "马斯克": "elonmusk",
    "特朗普": "realDonaldTrump",
    "川普": "realDonaldTrump",
    "拜登": "JoeBiden",
    "openai": "OpenAI",
    "奥特曼": "sama",
    "sam altman": "sama",
}


@dataclass
class BotConfig:
    app_id: str
    app_secret: str
    rss_base: str
    enable_translate: bool
    ai_base: str
    ai_model: str
    ai_key: str
    recipients_file: Path
    proactive_push_enabled: bool
    proactive_push_poll_seconds: int
    proactive_push_fetch_limit: int
    proactive_push_daily_time: str
    proactive_push_daily_max_items: int
    proactive_push_bootstrap_skip_existing: bool
    proactive_push_state_file: Path
    proactive_push_state_max_urls: int


def build_config(env: Dict[str, str]) -> BotConfig:
    return BotConfig(
        app_id=(env.get("FEISHU_APP_ID") or "").strip(),
        app_secret=(env.get("FEISHU_APP_SECRET") or "").strip(),
        rss_base=(env.get("FEISHU_BOT_RSS_BASE") or "http://127.0.0.1:1200").strip(),
        enable_translate=parse_bool(env.get("FEISHU_BOT_ENABLE_TRANSLATE", "true"), True),
        ai_base=normalize_ai_base(env.get("AI_API_BASE", "")),
        ai_model=strip_openai_prefix(env.get("AI_MODEL", "qwen2.5:1.5b")),
        ai_key=(env.get("AI_API_KEY") or "local_dummy_key").strip(),
        recipients_file=resolve_recipients_file(env.get("FEISHU_APP_RECIPIENTS_FILE", "")),
        proactive_push_enabled=parse_bool(env.get("FEISHU_APP_PUSH_ENABLED", "true"), True),
        proactive_push_poll_seconds=max(15, int(env.get("FEISHU_APP_PUSH_POLL_SECONDS", "60") or "60")),
        proactive_push_fetch_limit=max(20, int(env.get("FEISHU_APP_PUSH_FETCH_LIMIT", "200") or "200")),
        proactive_push_daily_time=(env.get("FEISHU_APP_PUSH_DAILY_TIME") or "08:00").strip(),
        proactive_push_daily_max_items=max(
            5, int(env.get("FEISHU_APP_PUSH_DAILY_MAX_ITEMS", "20") or "20")
        ),
        proactive_push_bootstrap_skip_existing=parse_bool(
            env.get("FEISHU_APP_PUSH_BOOTSTRAP_SKIP_EXISTING", "true"),
            True,
        ),
        proactive_push_state_file=resolve_data_path(
            env.get("FEISHU_APP_PUSH_STATE_FILE", ""),
            SCRIPT_DIR.parent / "output" / "feishu_app_push_state.json",
        ),
        proactive_push_state_max_urls=max(
            1000, int(env.get("FEISHU_APP_PUSH_STATE_MAX_URLS", "5000") or "5000")
        ),
    )


def extract_username(command_text: str) -> Optional[str]:
    text = normalize_command_text(command_text)
    if not text:
        return None
    lowered = text.lower()

    # 1) 中文别名 / 英文别名
    for alias, username in ALIAS_MAP.items():
        if alias.lower() in lowered:
            return username

    # 2) @username
    m = re.search(r"@([A-Za-z0-9_]{1,30})", text)
    if m:
        return m.group(1)

    # 3) 查/查看 username
    patterns = [
        r"(?:查|查看|看看|查询|获取)\s*([A-Za-z0-9_]{1,30})",
        r"([A-Za-z0-9_]{1,30})\s*(?:最新|最近)?\s*(?:推特|帖子|动态|tweet|x)",
    ]
    for pattern in patterns:
        m = re.search(pattern, text, flags=re.IGNORECASE)
        if m:
            return m.group(1)

    # 4) 纯用户名输入
    if re.fullmatch(r"[A-Za-z0-9_]{1,30}", text):
        return text
    return None


def normalize_command_text(command_text: str) -> str:
    text = str(command_text or "")
    text = re.sub(r"<at\b[^>]*>.*?</at>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"@_user_\d+", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def is_query_text(command_text: str) -> bool:
    text = normalize_command_text(command_text)
    if not text:
        return False
    if extract_username(text):
        return True
    return bool(
        re.search(r"(查|查看|看看|查询|获取|我要看|最新|推特|帖子|动态|tweet|x)", text, flags=re.IGNORECASE)
    )


def mark_message_seen(message_id: str) -> bool:
    value = str(message_id or "").strip()
    if not value:
        return False
    if value in SEEN_MESSAGE_IDS:
        return True
    if len(SEEN_MESSAGE_QUEUE) == MAX_SEEN_MESSAGE_IDS:
        dropped = SEEN_MESSAGE_QUEUE.popleft()
        SEEN_MESSAGE_IDS.discard(dropped)
    SEEN_MESSAGE_QUEUE.append(value)
    SEEN_MESSAGE_IDS.add(value)
    return False


def save_push_state(path: Path, state: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def load_push_state(path: Path) -> Dict[str, object]:
    if not path.exists():
        return {"bootstrapped": False, "last_daily_summary_date": "", "sent_urls": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"bootstrapped": False, "last_daily_summary_date": "", "sent_urls": []}
    if not isinstance(data, dict):
        return {"bootstrapped": False, "last_daily_summary_date": "", "sent_urls": []}
    if not isinstance(data.get("sent_urls"), list):
        data["sent_urls"] = []
    return data


def trim_sent_urls(urls: List[str], max_entries: int) -> List[str]:
    cleaned: List[str] = []
    seen: Set[str] = set()
    for url in reversed(urls):
        value = str(url or "").strip()
        if not value or value in seen:
            continue
        cleaned.append(value)
        seen.add(value)
        if len(cleaned) >= max_entries:
            break
    cleaned.reverse()
    return cleaned


def extract_summary_value(summary: str, label: str) -> str:
    text = str(summary or "").strip()
    if not text:
        return ""
    pattern = rf"{re.escape(label)}\s*:\s*([^|]+)"
    match = re.search(pattern, text)
    if not match:
        return ""
    return match.group(1).strip()


def extract_summary_url(summary: str, label: str) -> str:
    text = str(summary or "").strip()
    if not text:
        return ""
    pattern = rf"{re.escape(label)}\s*:\s*(https?://[^|\s]+)"
    match = re.search(pattern, text)
    if not match:
        return ""
    return match.group(1).strip()


def build_post_from_db_row(row: sqlite3.Row) -> PostItem:
    summary = str(row["summary"] or "").strip()
    image_url = extract_summary_url(summary, "图片")
    video_url = extract_summary_url(summary, "视频")
    brief = extract_summary_value(summary, "摘要") or extract_summary_value(summary, "内容")
    if not brief:
        brief = re.sub(r"(标签|摘要|内容|图片|视频)\s*:\s*[^|]+", " ", summary)
        brief = re.sub(r"\s+", " ", brief).strip()

    feed_name = str(row["feed_name"] or f"@{row['feed_id']}").strip()
    username = str(row["feed_id"] or "").strip()
    if username.startswith("x-"):
        username = username[2:]
    if not username:
        match = re.search(r"@([A-Za-z0-9_]{1,30})", feed_name)
        if match:
            username = match.group(1)

    return PostItem(
        username=username or "unknown",
        source_name=feed_name,
        title=str(row["title"] or "").strip() or "[无标题帖子]",
        url=str(row["url"] or "").strip(),
        published_at=str(row["published_at"] or "").strip(),
        body_text=brief,
        image_urls=[image_url] if image_url else [],
        video_urls=[video_url] if video_url else [],
        source="rss-db",
    )


def discover_rss_db_paths() -> List[Path]:
    now = datetime.now(CN_TIMEZONE)
    date_candidates = {
        now.strftime("%Y-%m-%d"),
        (now - timedelta(days=1)).strftime("%Y-%m-%d"),
    }
    paths: List[Path] = []
    root_dir = SCRIPT_DIR.parent
    base_dirs = [root_dir / "output" / "rss"]
    base_dirs.extend(sorted((root_dir / "output" / "shards").glob("*/rss")))
    base_dirs.extend(sorted((root_dir / "output" / "groups").glob("*/rss")))
    for base_dir in base_dirs:
        if not base_dir.exists():
            continue
        for date_text in sorted(date_candidates):
            candidate = base_dir / f"{date_text}.db"
            if candidate.exists():
                paths.append(candidate)
    unique: List[Path] = []
    seen: Set[str] = set()
    for path in paths:
        key = str(path.resolve())
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def load_recent_posts(limit_per_db: int) -> List[PostItem]:
    posts: List[PostItem] = []
    for db_path in discover_rss_db_paths():
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                """
                SELECT
                  i.id AS item_id,
                  i.title AS title,
                  i.url AS url,
                  i.published_at AS published_at,
                  i.summary AS summary,
                  i.created_at AS created_at,
                  i.feed_id AS feed_id,
                  f.name AS feed_name
                FROM rss_items i
                LEFT JOIN rss_feeds f ON f.id = i.feed_id
                ORDER BY i.id DESC
                LIMIT ?
                """,
                (limit_per_db,),
            ).fetchall()
        finally:
            conn.close()
        for row in rows:
            try:
                posts.append(build_post_from_db_row(row))
            except Exception as exc:
                logging.warning("failed to load db row from %s: %s", db_path, exc)
    return select_pending_posts(posts, set())


def select_pending_posts(posts: List[PostItem], sent_urls: Set[str]) -> List[PostItem]:
    pending: List[PostItem] = []
    seen_urls: Set[str] = set()
    for post in sorted(posts, key=lambda item: (format_china_time(item.published_at), item.url)):
        url = str(post.url or "").strip()
        if not url or url in sent_urls or url in seen_urls:
            continue
        seen_urls.add(url)
        pending.append(post)
    return pending


def build_daily_summary_text(posts: List[PostItem], cfg: BotConfig) -> str:
    now = datetime.now(CN_TIMEZONE).strftime("%Y-%m-%d %H:%M:%S")
    unique_posts: List[PostItem] = []
    seen_urls: Set[str] = set()
    for post in sorted(posts, key=lambda item: format_china_time(item.published_at), reverse=True):
        if post.url in seen_urls:
            continue
        seen_urls.add(post.url)
        unique_posts.append(post)

    lines = [
        "【飞书机器人｜今日X动态汇总】",
        f"时间: {now}",
        f"今日新增: {len(unique_posts)} 条",
        f"覆盖账号: {len({post.username for post in unique_posts})} 个",
    ]

    if not unique_posts:
        lines.append("今天还没有抓到新的帖子。")
        return "\n".join(lines)

    for index, post in enumerate(unique_posts[: cfg.proactive_push_daily_max_items], 1):
        title = post.title
        if cfg.enable_translate and not title.startswith("【") and not re.search(r"[\u4e00-\u9fff]", title):
            try:
                title = maybe_zh_translate(
                    source_text=title,
                    api_base=cfg.ai_base,
                    model=cfg.ai_model,
                    api_key=cfg.ai_key,
                ) or title
            except Exception:
                pass
        media_flags: List[str] = []
        if post.image_urls:
            media_flags.append("图片")
        if post.video_urls:
            media_flags.append("视频")
        suffix = f" [{' / '.join(media_flags)}]" if media_flags else ""
        lines.append(f"{index}. [{post.source_name}] {title}{suffix}")
        lines.append(f"   {format_china_time(post.published_at)}")
        lines.append(f"   {post.url}")
    return "\n".join(lines)


def maybe_register_p2p_recipient(
    cfg: BotConfig,
    *,
    chat_type: str,
    chat_id: str,
    open_id: str = "",
    user_id: str = "",
    tenant_key: str = "",
    source: str = "",
) -> bool:
    chat_type_value = str(chat_type or "").strip().lower()
    if chat_type_value != "p2p":
        return False
    return upsert_p2p_recipient(
        cfg.recipients_file,
        chat_id=chat_id,
        open_id=open_id,
        user_id=user_id,
        tenant_key=tenant_key,
        source=source,
    )


def run_proactive_push_loop(cfg: BotConfig) -> None:
    logging.info("feishu proactive push loop started")
    state = load_push_state(cfg.proactive_push_state_file)
    waiting_for_recipients_logged = False

    while True:
        try:
            recipients = list_active_recipients(cfg.recipients_file)
            if not recipients:
                if not waiting_for_recipients_logged:
                    logging.info(
                        "no active feishu app recipients yet; waiting for first private chat before proactive push"
                    )
                    waiting_for_recipients_logged = True
                time.sleep(cfg.proactive_push_poll_seconds)
                continue
            if waiting_for_recipients_logged:
                logging.info("active feishu app recipients detected: count=%s", len(recipients))
                waiting_for_recipients_logged = False

            posts = load_recent_posts(cfg.proactive_push_fetch_limit)
            current_urls = [post.url for post in posts if post.url]
            sent_urls = trim_sent_urls(
                [str(url) for url in state.get("sent_urls", [])] + [],
                cfg.proactive_push_state_max_urls,
            )
            sent_url_set = set(sent_urls)

            if not state.get("bootstrapped") and cfg.proactive_push_bootstrap_skip_existing:
                state["bootstrapped"] = True
                state["sent_urls"] = trim_sent_urls(
                    sent_urls + current_urls,
                    cfg.proactive_push_state_max_urls,
                )
                save_push_state(cfg.proactive_push_state_file, state)
                logging.info("feishu proactive push bootstrap complete, existing=%s", len(current_urls))
            else:
                if not state.get("bootstrapped"):
                    state["bootstrapped"] = True
                    save_push_state(cfg.proactive_push_state_file, state)
                pending_posts = select_pending_posts(posts, sent_url_set)
                for post in pending_posts:
                    text = build_reply_text(post, cfg)
                    sent_count, _ = send_text_to_recipients(
                        app_id=cfg.app_id,
                        app_secret=cfg.app_secret,
                        recipients_file=cfg.recipients_file,
                        text=text,
                    )
                    if sent_count <= 0:
                        logging.info("skipped proactive push because no recipients accepted delivery")
                        break
                    state["sent_urls"] = trim_sent_urls(
                        list(state.get("sent_urls", [])) + [post.url],
                        cfg.proactive_push_state_max_urls,
                    )
                    save_push_state(cfg.proactive_push_state_file, state)
                    logging.info(
                        "feishu proactive push sent: username=%s recipients=%s",
                        post.username,
                        sent_count,
                    )

            now = datetime.now(CN_TIMEZONE)
            today = now.strftime("%Y-%m-%d")
            if (
                now.strftime("%H:%M") >= cfg.proactive_push_daily_time
                and state.get("last_daily_summary_date") != today
            ):
                today_posts = [
                    post
                    for post in posts
                    if format_china_time(post.published_at).startswith(today)
                ]
                summary_text = build_daily_summary_text(today_posts, cfg)
                sent_count, _ = send_text_to_recipients(
                    app_id=cfg.app_id,
                    app_secret=cfg.app_secret,
                    recipients_file=cfg.recipients_file,
                    text=summary_text,
                )
                if sent_count <= 0:
                    logging.info("skipped daily summary because no recipients accepted delivery")
                    time.sleep(cfg.proactive_push_poll_seconds)
                    continue
                state["last_daily_summary_date"] = today
                save_push_state(cfg.proactive_push_state_file, state)
                logging.info("feishu daily summary sent: recipients=%s items=%s", sent_count, len(today_posts))
        except Exception as exc:
            logging.exception("feishu proactive push loop error: %s", exc)

        time.sleep(cfg.proactive_push_poll_seconds)


def fetch_latest_post(username: str, rss_base: str) -> Tuple[Optional[PostItem], str]:
    try:
        post = fetch_from_rsshub(rss_base, username=username)
        if post:
            return post, "rsshub"
    except Exception:
        pass

    try:
        post = fetch_from_nitter(username=username)
        if post:
            return post, "nitter"
    except Exception:
        pass

    db_path = resolve_rss_db_path()
    if db_path:
        post = fetch_from_local_sqlite(db_path, username=username)
        if post:
            return post, "sqlite"

    return None, "none"


def build_reply_text(post: PostItem, cfg: BotConfig) -> str:
    original_title = post.title or "[无标题帖子]"
    original_body = post.body_text or ""
    translated_title = ""
    translated_body = ""
    summary = ""
    tag_line = ""

    meaningful = has_meaningful_text(f"{original_title}\n{original_body}")
    if not meaningful:
        if post.video_urls:
            summary = "该帖子主要为视频内容，建议点开原帖查看完整视频。"
            tag_line = "#视频 #媒体帖"
        elif post.image_urls:
            summary = "该帖子主要为图片内容，建议查看配图与原帖。"
            tag_line = "#图片 #媒体帖"
        else:
            summary = "该帖可解析文本不足，建议直接查看原帖。"
            tag_line = "#X动态"
        original_body = original_body or "（未提取到可用正文文本）"
    elif cfg.enable_translate:
        try:
            title_cn = maybe_zh_translate(
                source_text=original_title, api_base=cfg.ai_base, model=cfg.ai_model, api_key=cfg.ai_key
            )
            body_cn = maybe_zh_translate(
                source_text=original_body, api_base=cfg.ai_base, model=cfg.ai_model, api_key=cfg.ai_key
            )
            summary = summarize_cn(
                title_cn=title_cn,
                body_cn=body_cn,
                api_base=cfg.ai_base,
                model=cfg.ai_model,
                api_key=cfg.ai_key,
            )
            tag_line = tags_cn(
                title_cn=title_cn,
                body_cn=body_cn,
                api_base=cfg.ai_base,
                model=cfg.ai_model,
                api_key=cfg.ai_key,
            )
            translated_title = title_cn or ""
            translated_body = body_cn or ""
        except Exception as exc:
            logging.warning("翻译/总结失败，回退原文: %s", exc)

    return build_post_message_text(
        header=f"【@{post.username} 最新帖子】",
        author_line=post.source_name,
        published_at=post.published_at,
        original_title=original_title,
        translated_title=translated_title,
        summary=summary,
        tags=tag_line,
        original_body=original_body,
        translated_body=translated_body,
        image_urls=post.image_urls,
        video_urls=post.video_urls,
        post_url=post.url,
        body_limit=700,
    )


def make_handler(cfg: BotConfig):
    import lark_oapi as lark
    from lark_oapi.api.im.v1 import (
        ReplyMessageRequest,
        ReplyMessageRequestBody,
    )

    client = lark.Client.builder().app_id(cfg.app_id).app_secret(cfg.app_secret).build()

    def reply(message_id: str, text: str) -> None:
        request = (
            ReplyMessageRequest.builder()
            .message_id(message_id)
            .request_body(
                ReplyMessageRequestBody.builder()
                .content(json.dumps({"text": text}, ensure_ascii=False))
                .msg_type("text")
                .build()
            )
            .build()
        )
        response = client.im.v1.message.reply(request)
        if not response.success():
            logging.error("reply failed: code=%s msg=%s", response.code, response.msg)
            return
        logging.info("reply sent: message_id=%s", message_id)

    def register_from_message_event(event, message, chat_type: str, source: str) -> None:
        sender = getattr(event, "sender", None)
        sender_id = getattr(sender, "sender_id", None)
        open_id = getattr(sender_id, "open_id", "") if sender_id else ""
        user_id = getattr(sender_id, "user_id", "") if sender_id else ""
        tenant_key = getattr(sender, "tenant_key", "") if sender else ""
        added = maybe_register_p2p_recipient(
            cfg,
            chat_type=chat_type,
            chat_id=getattr(message, "chat_id", "") or "",
            open_id=open_id or "",
            user_id=user_id or "",
            tenant_key=tenant_key or "",
            source=source,
        )
        if added:
            logging.info("registered new p2p recipient from message: chat_id=%s", getattr(message, "chat_id", ""))

    def do_message(data) -> None:
        event = data.event
        if not event or not event.message:
            return
        message = event.message
        if mark_message_seen(getattr(message, "message_id", "")):
            logging.info("duplicate message ignored: id=%s", getattr(message, "message_id", ""))
            return
        chat_type = getattr(message, "chat_type", "") or getattr(event, "chat_type", "")
        logging.info(
            "incoming message: id=%s type=%s chat_type=%s",
            message.message_id,
            message.message_type,
            chat_type or "unknown",
        )
        register_from_message_event(event, message, str(chat_type or ""), "message")
        if message.message_type != "text":
            logging.info("non-text message ignored: id=%s", message.message_id)
            reply(message.message_id, "请发文本命令。\n" + HELP_TEXT)
            return

        try:
            content_obj = json.loads(message.content or "{}")
            text = normalize_command_text(str(content_obj.get("text", "")).strip())
        except Exception:
            text = ""
        logging.info("incoming text: id=%s text=%s", message.message_id, text[:120])

        chat_type_lower = str(chat_type or "").strip().lower()
        if chat_type_lower in {"group", "chat"} and not is_query_text(text):
            logging.info("non-query group message ignored: id=%s", message.message_id)
            return

        username = extract_username(text)
        if not username:
            logging.info("username not recognized: id=%s", message.message_id)
            reply(message.message_id, "没识别到账号。\n" + HELP_TEXT)
            return

        post, source = fetch_latest_post(username=username, rss_base=cfg.rss_base)
        if not post:
            logging.warning("post not found: username=%s", username)
            reply(
                message.message_id,
                f"未找到 @{username} 最新帖子（已尝试 RSSHub/Nitter/本地缓存）。",
            )
            return

        text_reply = build_reply_text(post, cfg)
        reply(message.message_id, text_reply)
        logging.info("handled query: username=%s source=%s", username, source)

    def do_p2p_entered(data) -> None:
        event = getattr(data, "event", None)
        if not event:
            return
        operator_id = getattr(event, "operator_id", None)
        open_id = getattr(operator_id, "open_id", "") if operator_id else ""
        user_id = getattr(operator_id, "user_id", "") if operator_id else ""
        chat_id = getattr(event, "chat_id", "") or ""
        added = maybe_register_p2p_recipient(
            cfg,
            chat_type="p2p",
            chat_id=chat_id,
            open_id=open_id or "",
            user_id=user_id or "",
            source="p2p_entered",
        )
        if not added:
            return
        logging.info("registered new p2p recipient from chat enter: chat_id=%s", chat_id)
        try:
            send_text_message(
                app_id=cfg.app_id,
                app_secret=cfg.app_secret,
                receive_id=chat_id,
                receive_id_type="chat_id",
                text=(
                    "已连接飞书机器人。\n"
                    "后续会实时推送你关注列表里的新帖子，并在每天 08:00 发送汇总。\n"
                    "也可以直接发送：查看openai最新的动态"
                ),
            )
        except Exception as exc:
            logging.warning("failed to send onboarding message: %s", exc)

    builder = lark.EventDispatcherHandler.builder("", "")
    if hasattr(builder, "register_im_message_receive_v1"):
        builder = builder.register_im_message_receive_v1(do_message)
        logging.info("event handler registered: im_message_receive_v1 (group+p2)")
    else:
        builder = builder.register_p2_im_message_receive_v1(do_message)
        logging.info("event handler registered: im_message_receive_v1 (SDK alias: register_p2_im_message_receive_v1)")
    if hasattr(builder, "register_p2_im_chat_access_event_bot_p2p_chat_entered_v1"):
        builder = builder.register_p2_im_chat_access_event_bot_p2p_chat_entered_v1(do_p2p_entered)
        logging.info("event handler registered: p2.im.chat.access_event.bot_p2p_chat_entered_v1")
    event_handler = builder.build()
    return event_handler


def run_self_test(cfg: BotConfig, command_text: str) -> int:
    username = extract_username(command_text)
    if not username:
        print("未识别到账号。")
        print(HELP_TEXT)
        return 2
    post, source = fetch_latest_post(username=username, rss_base=cfg.rss_base)
    if not post:
        print(f"未找到 @{username} 最新帖子（source={source}）")
        return 1
    print(build_reply_text(post, cfg))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="飞书指令机器人（长连接）")
    parser.add_argument(
        "--self-test",
        default="",
        help="本地自测命令文本，不连接飞书。例如：--self-test '我要看马斯克最新推特'",
    )
    args = parser.parse_args()

    env = load_env_file(ENV_PATH)
    cfg = build_config(env)

    if args.self_test:
        return run_self_test(cfg, args.self_test)

    if not cfg.app_id or not cfg.app_secret:
        print(
            "[ERROR] 请先在 .env 配置 FEISHU_APP_ID / FEISHU_APP_SECRET",
            file=sys.stderr,
        )
        return 2

    try:
        import lark_oapi as lark
    except Exception:
        print(
            "[ERROR] 缺少依赖 lark-oapi。请先执行：python3 -m pip install --user lark-oapi",
            file=sys.stderr,
        )
        return 2

    log_dir = SCRIPT_DIR.parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    max_bytes = int(os.getenv("FEISHU_BOT_LOG_MAX_BYTES", "5242880"))
    backups = int(os.getenv("FEISHU_BOT_LOG_BACKUPS", "5"))

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.handlers = []
    formatter = logging.Formatter("[%(asctime)s] %(levelname)s %(message)s")

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    root_logger.addHandler(stream_handler)

    file_handler = RotatingFileHandler(
        log_dir / "feishu-command-bot.log",
        maxBytes=max_bytes,
        backupCount=backups,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    logging.info("starting feishu command bot (long connection)")
    logging.info("recipient registry: %s", cfg.recipients_file)

    if cfg.proactive_push_enabled:
        proactive_thread = threading.Thread(
            target=run_proactive_push_loop,
            args=(cfg,),
            daemon=True,
            name="feishu-proactive-push",
        )
        proactive_thread.start()
        logging.info(
            "feishu proactive push enabled: poll=%ss daily=%s",
            cfg.proactive_push_poll_seconds,
            cfg.proactive_push_daily_time,
        )
    else:
        logging.info("feishu proactive push disabled")

    event_handler = make_handler(cfg)
    ws_client = lark.ws.Client(
        cfg.app_id,
        cfg.app_secret,
        event_handler=event_handler,
        log_level=lark.LogLevel.INFO,
    )
    ws_client.start()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
