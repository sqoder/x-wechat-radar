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
import sys
from collections import deque
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Deque, Dict, Optional, Set, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from x_latest_post import (  # noqa: E402
    ENV_PATH,
    PostItem,
    fetch_from_local_sqlite,
    fetch_from_nitter,
    fetch_from_rsshub,
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


def parse_bool(value: str, default: bool = False) -> bool:
    text = str(value or "").strip().lower()
    if not text:
        return default
    return text in {"1", "true", "yes", "y", "on"}


def build_config(env: Dict[str, str]) -> BotConfig:
    return BotConfig(
        app_id=(env.get("FEISHU_APP_ID") or "").strip(),
        app_secret=(env.get("FEISHU_APP_SECRET") or "").strip(),
        rss_base=(env.get("FEISHU_BOT_RSS_BASE") or "http://127.0.0.1:1200").strip(),
        enable_translate=parse_bool(env.get("FEISHU_BOT_ENABLE_TRANSLATE", "true"), True),
        ai_base=normalize_ai_base(env.get("AI_API_BASE", "")),
        ai_model=strip_openai_prefix(env.get("AI_MODEL", "qwen2.5:1.5b")),
        ai_key=(env.get("AI_API_KEY") or "local_dummy_key").strip(),
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
    title = post.title
    body = post.body_text
    summary = ""
    tag_line = ""

    meaningful = has_meaningful_text(f"{title}\n{body}")
    if not meaningful:
        if post.video_urls:
            title = "该帖为纯视频帖（原文文本较少）"
            summary = "该帖子主要为视频内容，建议点开原帖查看完整视频。"
            tag_line = "#视频 #媒体帖"
        elif post.image_urls:
            title = "该帖为图片帖（原文文本较少）"
            summary = "该帖子主要为图片内容，建议查看配图与原帖。"
            tag_line = "#图片 #媒体帖"
        else:
            title = "该帖文本信息较少"
            summary = "该帖可解析文本不足，建议直接查看原帖。"
            tag_line = "#X动态"
        body = body or "（未提取到可用正文文本）"
    elif cfg.enable_translate:
        try:
            title_cn = maybe_zh_translate(
                source_text=title, api_base=cfg.ai_base, model=cfg.ai_model, api_key=cfg.ai_key
            )
            body_cn = maybe_zh_translate(
                source_text=body, api_base=cfg.ai_base, model=cfg.ai_model, api_key=cfg.ai_key
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
            title = title_cn or title
            body = body_cn or body
        except Exception as exc:
            logging.warning("翻译/总结失败，回退原文: %s", exc)

    lines = [
        f"【@{post.username} 最新帖子】",
        f"来源: {post.source_name} ({post.source})",
        f"时间: {post.published_at or '未知'}",
        f"标题: {title}",
    ]
    if summary:
        lines.append(f"总结: {summary}")
    if tag_line:
        lines.append(f"标签: {tag_line}")
    if body:
        lines.append(f"内容: {body[:700]}")
    if post.image_urls:
        lines.append(f"图片: {post.image_urls[0]}")
    if post.video_urls:
        lines.append(f"视频: {post.video_urls[0]}")
    lines.append(f"原帖: {post.url}")
    return "\n".join(lines)


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

    builder = lark.EventDispatcherHandler.builder("", "")
    if hasattr(builder, "register_im_message_receive_v1"):
        builder = builder.register_im_message_receive_v1(do_message)
        logging.info("event handler registered: im_message_receive_v1 (group+p2)")
    else:
        builder = builder.register_p2_im_message_receive_v1(do_message)
        logging.info("event handler registered: im_message_receive_v1 (SDK alias: register_p2_im_message_receive_v1)")
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
