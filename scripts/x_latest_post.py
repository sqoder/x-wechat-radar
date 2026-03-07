#!/usr/bin/env python3
# coding: utf-8
"""
按需查询 X 账号最新帖子（支持本地翻译/总结，可选 OCR/ASR）。

目标：
1) 可随时查询任意账号最新帖（如 @realDonaldTrump）
2) 优先走本地 RSSHub，失败时回退本地 SQLite 历史库
3) 全部使用本地模型能力（Ollama + 可选 PaddleOCR / faster-whisper）
4) 支持推送到企业微信或飞书
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import html
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import textwrap
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Dict, List, Optional, Sequence
from urllib.parse import quote
import xml.etree.ElementTree as ET

import requests
from zoneinfo import ZoneInfo

from feishu_app_support import (
    has_feishu_app_push_target,
    resolve_recipients_file,
    send_text_to_recipients,
)


ROOT_DIR = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT_DIR / ".env"
RSS_DB_DIR = ROOT_DIR / "output" / "rss"
CN_TIMEZONE = ZoneInfo("Asia/Shanghai")


@dataclass
class PostItem:
    username: str
    source_name: str
    title: str
    url: str
    published_at: str
    body_text: str
    image_urls: List[str]
    video_urls: List[str]
    source: str  # rsshub | sqlite


def load_env_file(path: Path) -> Dict[str, str]:
    env: Dict[str, str] = {}
    if not path.exists():
        return env
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip()
    return env


def resolve_rss_db_path(preferred_date: Optional[str] = None) -> Optional[Path]:
    """解析可用的 RSS SQLite 路径，优先当天文件，回退到最新文件。"""
    if not RSS_DB_DIR.exists():
        return None

    if preferred_date:
        candidate = RSS_DB_DIR / f"{preferred_date}.db"
        if candidate.exists():
            return candidate

    all_dbs = sorted(RSS_DB_DIR.glob("*.db"))
    if not all_dbs:
        return None
    return all_dbs[-1]


def strip_openai_prefix(model_name: str) -> str:
    name = (model_name or "").strip()
    if name.startswith("openai/"):
        return name[len("openai/") :]
    return name


def _running_in_docker() -> bool:
    """判断当前进程是否运行在容器内。"""
    hint = str(os.getenv("RUNNING_IN_DOCKER", "")).strip().lower()
    if hint in {"1", "true", "yes", "on"}:
        return True
    if hint in {"0", "false", "no", "off"}:
        return False
    return Path("/.dockerenv").exists()


def normalize_ai_base(ai_base: str) -> str:
    base = (ai_base or "").strip()
    if not base:
        return "http://127.0.0.1:11434/v1"
    base = base.rstrip("/")
    # 宿主机脚本无法解析 host.docker.internal，容器内则需要保留该地址。
    if "host.docker.internal" in base and not _running_in_docker():
        base = base.replace("host.docker.internal", "127.0.0.1")
    return base


def is_chinese_text(text: str) -> bool:
    if not text:
        return False
    zh_count = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    return zh_count >= 4


def has_meaningful_text(text: str) -> bool:
    value = (text or "").strip().lower()
    if not value:
        return False
    value = re.sub(r"https?://\S+", "", value)
    value = re.sub(r"\s+", " ", value).strip()
    if value in {"video", "photo", "image", "gif", "pinned:", "rt"}:
        return False
    # 至少有一些可解释语义，避免纯媒体帖触发模型幻觉翻译
    alpha_num = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", value)
    return len(alpha_num) >= 12


def ollama_chat(
    *,
    api_base: str,
    model: str,
    api_key: str,
    system: str,
    user: str,
    temperature: float = 0.2,
    timeout: int = 120,
) -> str:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
    }
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    resp = requests.post(
        f"{api_base}/chat/completions",
        headers=headers,
        json=payload,
        timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()
    return str(data["choices"][0]["message"]["content"]).strip()


def maybe_zh_translate(
    *,
    source_text: str,
    api_base: str,
    model: str,
    api_key: str,
) -> str:
    if not source_text.strip():
        return ""
    translated = ollama_chat(
        api_base=api_base,
        model=model,
        api_key=api_key,
        system=(
            "你是严格翻译助手。输出必须是简体中文。"
            "保留 URL、@用户名、#标签、$代码，不要额外解释。"
        ),
        user=source_text,
        temperature=0.0,
    )
    if is_chinese_text(translated):
        return translated
    # 兜底再翻一次，避免小模型偶发回英文。
    return ollama_chat(
        api_base=api_base,
        model=model,
        api_key=api_key,
        system="请把输入完整翻译成简体中文。只输出中文翻译结果。",
        user=source_text,
        temperature=0.0,
    )


def summarize_cn(
    *,
    title_cn: str,
    body_cn: str,
    api_base: str,
    model: str,
    api_key: str,
) -> str:
    summary = ollama_chat(
        api_base=api_base,
        model=model,
        api_key=api_key,
        system="你是中文科技编辑。写一句20-50字中文总结。只输出一句话。",
        user=f"标题：{title_cn}\n正文：{body_cn}",
        temperature=0.2,
    )
    if is_chinese_text(summary):
        return summary
    return maybe_zh_translate(
        source_text=summary, api_base=api_base, model=model, api_key=api_key
    )


def tags_cn(
    *,
    title_cn: str,
    body_cn: str,
    api_base: str,
    model: str,
    api_key: str,
) -> str:
    tags = ollama_chat(
        api_base=api_base,
        model=model,
        api_key=api_key,
        system=(
            "你是标签提取助手。输出 3-5 个标签，格式严格为："
            "#标签1 #标签2 #标签3。只输出标签。"
        ),
        user=f"标题：{title_cn}\n正文：{body_cn}",
        temperature=0.2,
    )
    tags = re.sub(r"\s+", " ", tags).strip()
    if "#" not in tags:
        return "#AI #X动态"
    return tags


def extract_text_from_html(html_text: str) -> str:
    if not html_text:
        return ""
    text = html.unescape(html_text)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def dedupe_keep_order(items: Sequence[str]) -> List[str]:
    result: List[str] = []
    seen = set()
    for item in items:
        v = str(item or "").strip()
        if not v or v in seen:
            continue
        seen.add(v)
        result.append(v)
    return result


def format_china_time(raw_time: str) -> str:
    value = str(raw_time or "").strip()
    if not value:
        return "未知"

    dt: Optional[datetime] = None
    try:
        dt = parsedate_to_datetime(value)
    except Exception:
        dt = None

    if dt is None:
        iso_text = value.replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(iso_text)
        except Exception:
            dt = None

    if dt is None:
        return value

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone(timedelta(hours=8)))
    return dt.astimezone(CN_TIMEZONE).strftime("%Y-%m-%d %H:%M:%S")


def extract_media_urls(raw_html: str) -> Dict[str, List[str]]:
    if not raw_html:
        return {"image": [], "video": []}
    images = re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', raw_html, flags=re.I)
    videos = re.findall(r'<video[^>]+src=["\']([^"\']+)["\']', raw_html, flags=re.I)
    images = [html.unescape(u) for u in images]
    videos = [html.unescape(u) for u in videos]
    return {"image": dedupe_keep_order(images), "video": dedupe_keep_order(videos)}


def is_probable_video_post(
    *,
    original_title: str,
    original_body: str,
    image_urls: Optional[Sequence[str]] = None,
    video_urls: Optional[Sequence[str]] = None,
) -> bool:
    if video_urls:
        return True

    title = str(original_title or "").strip().lower()
    body = str(original_body or "").strip().lower()
    if title == "video" or title.endswith(": video"):
        return True
    if re.search(r"\bvideo\b", body):
        return True

    for image_url in image_urls or []:
        lowered = str(image_url or "").strip().lower()
        if "video_thumb" in lowered or "ext_tw_video_thumb" in lowered or "amplify_video_thumb" in lowered:
            return True
    return False


def parse_first_rss_item(xml_text: str, username: str) -> Optional[PostItem]:
    if not xml_text.strip():
        return None
    root = ET.fromstring(xml_text)
    channel = root.find("channel")
    if channel is None:
        return None
    title = channel.findtext("title", default=f"Twitter @{username}")
    source_name = title.replace("Twitter ", "").strip() or f"@{username}"
    item = channel.find("item")
    if item is None:
        return None

    item_title = item.findtext("title", default="").strip()
    item_link = item.findtext("link", default="").strip()
    pub_date = item.findtext("pubDate", default="").strip()
    desc_html = item.findtext("description", default="") or ""
    media = extract_media_urls(desc_html)
    body = extract_text_from_html(desc_html)
    if not item_title:
        item_title = body[:120] if body else "[无标题帖子]"

    return PostItem(
        username=username,
        source_name=source_name,
        title=item_title,
        url=item_link,
        published_at=pub_date,
        body_text=body,
        image_urls=media["image"],
        video_urls=media["video"],
        source="rsshub",
    )


def fetch_from_rsshub(rss_base: str, username: str, timeout: int = 25) -> Optional[PostItem]:
    route = f"{rss_base.rstrip('/')}/twitter/user/{quote(username)}"
    resp = requests.get(route, timeout=timeout)
    resp.raise_for_status()
    return parse_first_rss_item(resp.text, username=username)


def _to_x_status_url_from_nitter(link: str, username: str) -> str:
    text = (link or "").strip()
    m = re.search(r"/status/(\d+)", text)
    if not m:
        return text
    return f"https://x.com/{username}/status/{m.group(1)}"


def fetch_from_nitter(username: str, timeout: int = 25) -> Optional[PostItem]:
    url = f"https://nitter.net/{quote(username)}/rss"
    resp = requests.get(url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()

    root = ET.fromstring(resp.text)
    channel = root.find("channel")
    if channel is None:
        return None

    source_name = channel.findtext("title", default=f"@{username}").strip()
    items = channel.findall("item")
    if not items:
        return None

    def is_meaningful_item(item: ET.Element) -> bool:
        title = (item.findtext("title") or "").strip().lower()
        if title.startswith("pinned:"):
            return False
        desc = item.findtext("description", default="") or ""
        body = extract_text_from_html(desc).strip().lower()
        generic_titles = {"video", "photo", "image", "gif", "pinned:"}
        if title in generic_titles and body in {"", "video", "photo", "image", "gif"}:
            return False
        return True

    selected = None
    for item in items:
        if not is_meaningful_item(item):
            continue
        selected = item
        break
    if selected is None:
        selected = items[0]

    raw_title = (selected.findtext("title") or "").strip()
    raw_link = (selected.findtext("link") or "").strip()
    published_at = (selected.findtext("pubDate") or "").strip()
    desc_html = selected.findtext("description", default="") or ""

    media = extract_media_urls(desc_html)
    body = extract_text_from_html(desc_html)
    if not raw_title:
        raw_title = body[:120] if body else "[无标题帖子]"

    status_url = _to_x_status_url_from_nitter(raw_link, username=username)
    return PostItem(
        username=username,
        source_name=source_name,
        title=raw_title,
        url=status_url or raw_link,
        published_at=published_at,
        body_text=body,
        image_urls=media["image"],
        video_urls=media["video"],
        source="nitter",
    )


def fetch_from_local_sqlite(db_path: Path, username: str) -> Optional[PostItem]:
    if not db_path.exists():
        return None
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            """
            SELECT
              i.title AS title,
              i.url AS url,
              i.published_at AS published_at,
              i.summary AS summary,
              f.name AS feed_name
            FROM rss_items i
            LEFT JOIN rss_feeds f ON f.id = i.feed_id
            WHERE lower(i.url) LIKE lower(?)
            ORDER BY datetime(i.published_at) DESC, i.id DESC
            LIMIT 1
            """,
            (f"%/{username}/status/%",),
        ).fetchone()
        if row is None:
            return None
        summary = str(row["summary"] or "")
        image_urls = re.findall(r"图片\s*:\s*(https?://[^|\s]+)", summary)
        video_urls = re.findall(r"视频\s*:\s*(https?://[^|\s]+)", summary)
        image_urls = [html.unescape(x) for x in image_urls]
        video_urls = [html.unescape(x) for x in video_urls]
        body = re.sub(r"\b(图片|视频)\s*:\s*https?://[^|\s]+\s*\|?\s*", "", summary)
        body = body.replace("内容:", "").replace("摘要:", "")
        body = re.sub(r"\s*\|\s*", " ", body).strip()
        return PostItem(
            username=username,
            source_name=str(row["feed_name"] or f"@{username}"),
            title=str(row["title"] or "").strip(),
            url=str(row["url"] or "").strip(),
            published_at=str(row["published_at"] or "").strip(),
            body_text=body,
            image_urls=dedupe_keep_order(image_urls),
            video_urls=dedupe_keep_order(video_urls),
            source="sqlite",
        )
    finally:
        conn.close()


def download_bytes(url: str, timeout: int = 40) -> bytes:
    resp = requests.get(url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    return resp.content


def ocr_with_paddle(image_path: Path) -> str:
    try:
        from paddleocr import PaddleOCR  # type: ignore
    except Exception:
        return ""
    try:
        ocr = PaddleOCR(use_angle_cls=True, lang="ch")
        result = ocr.ocr(str(image_path), cls=True)
        texts: List[str] = []
        for line in result or []:
            for cell in line or []:
                if len(cell) >= 2 and isinstance(cell[1], (list, tuple)):
                    txt = str(cell[1][0]).strip()
                    if txt:
                        texts.append(txt)
        return " ".join(texts).strip()
    except Exception:
        return ""


def transcribe_video_with_faster_whisper(video_path: Path) -> str:
    try:
        from faster_whisper import WhisperModel  # type: ignore
    except Exception:
        return ""

    with tempfile.TemporaryDirectory(prefix="xradar_asr_") as td:
        wav_path = Path(td) / "audio.wav"
        try:
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-i",
                    str(video_path),
                    "-vn",
                    "-acodec",
                    "pcm_s16le",
                    "-ar",
                    "16000",
                    "-ac",
                    "1",
                    str(wav_path),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            return ""

        try:
            model = WhisperModel("small", device="auto", compute_type="int8")
            segments, _ = model.transcribe(str(wav_path), vad_filter=True, beam_size=1)
            texts = [seg.text.strip() for seg in segments if seg.text and seg.text.strip()]
            return " ".join(texts).strip()
        except Exception:
            return ""


def wework_post_json(webhook: str, payload: Dict[str, object]) -> Dict[str, object]:
    resp = requests.post(webhook, json=payload, timeout=30)
    data = {}
    try:
        data = resp.json()
    except Exception:
        data = {"raw": resp.text[:300]}
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code}: {data}")
    if isinstance(data, dict) and data.get("errcode") not in (0, None):
        raise RuntimeError(f"WeWork error: {data}")
    return data


def feishu_post_json(webhook: str, payload: Dict[str, object]) -> Dict[str, object]:
    resp = requests.post(webhook, json=payload, timeout=30)
    try:
        data = resp.json()
    except Exception:
        data = {"raw": resp.text[:300]}

    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code}: {data}")
    if isinstance(data, dict) and data.get("code") not in (0, None):
        code = data.get("code")
        if code == 19007:
            raise RuntimeError(
                "Feishu Bot Not Enabled：当前 webhook 非自定义机器人，"
                "或机器人未启用。请在目标群添加“自定义机器人”并使用其 webhook。"
            )
        raise RuntimeError(f"Feishu error: {data}")
    return data


def truncate_utf8(text: str, max_bytes: int = 18000) -> str:
    raw = (text or "").encode("utf-8")
    if len(raw) <= max_bytes:
        return text
    suffix = "\n...(内容过长，已截断)"
    suffix_bytes = suffix.encode("utf-8")
    keep_bytes = max(0, max_bytes - len(suffix_bytes))
    clipped = raw[:keep_bytes]
    while clipped:
        try:
            return clipped.decode("utf-8") + suffix
        except UnicodeDecodeError:
            clipped = clipped[:-1]
    return suffix


def _truncate_preview(text: str, limit: int) -> str:
    value = str(text or "").strip()
    if not value:
        return ""
    return value[:limit]


def _normalize_author_line(*, author_line: str = "", source_line: str = "") -> str:
    value = str(author_line or source_line or "").strip()
    if not value:
        return ""
    value = re.sub(r"^(来源|数据源)\s*:\s*", "", value)
    value = re.sub(r"\s+\((rsshub|nitter|sqlite|rss-db)\)\s*$", "", value, flags=re.IGNORECASE)
    return value.strip()


def _pick_message_title(*, header: str, original_title: str, translated_title: str) -> str:
    title = str(translated_title or original_title or "").strip()
    if title:
        return title
    return str(header or "[无标题帖子]").strip()


def build_post_message_text(
    *,
    header: str,
    author_line: str = "",
    source_line: str = "",
    published_at: str,
    original_title: str,
    translated_title: str = "",
    summary: str = "",
    tags: str = "",
    original_body: str = "",
    translated_body: str = "",
    image_urls: Optional[Sequence[str]] = None,
    video_urls: Optional[Sequence[str]] = None,
    ocr_text: str = "",
    asr_text: str = "",
    post_url: str = "",
    body_limit: int = 800,
) -> str:
    image_list = list(image_urls or [])
    video_list = list(video_urls or [])
    display_title = _truncate_preview(
        _pick_message_title(
            header=header,
            original_title=original_title,
            translated_title=translated_title,
        ),
        120,
    )
    meta_parts = []
    normalized_author = _normalize_author_line(author_line=author_line, source_line=source_line)
    if normalized_author:
        meta_parts.append(normalized_author)
    formatted_time = format_china_time(published_at)
    if formatted_time:
        meta_parts.append(formatted_time)

    lines = [
        f"🧠 {display_title}",
    ]
    if meta_parts:
        lines.append(" | ".join(meta_parts))

    core_lines: List[str] = []
    if summary:
        core_lines.append(f"总结：{summary}")
    original_body_preview = _truncate_preview(original_body, body_limit)
    translated_body_preview = _truncate_preview(translated_body, body_limit)
    original_core = original_body_preview or str(original_title or "[无标题帖子]").strip()
    translated_core = translated_body_preview or str(translated_title or "").strip()
    if original_core:
        core_lines.append(f"原文：{original_core}")
    if translated_core:
        core_lines.append(f"翻译：{translated_core}")
    if ocr_text:
        core_lines.append(f"图片OCR：{ocr_text}")
    if asr_text:
        core_lines.append(f"视频ASR：{asr_text}")

    if core_lines:
        lines.extend(["", "核心内容：", *core_lines])

    media_lines: List[str] = []
    if image_list:
        media_lines.append(f"图片：{image_list[0]}")
    if video_list:
        media_lines.append(f"视频：{video_list[0]}")
    elif is_probable_video_post(
        original_title=original_title,
        original_body=original_body,
        image_urls=image_list,
        video_urls=video_list,
    ):
        media_lines.append("视频：该帖为视频帖，当前源仅返回预览图，请点开原帖观看")

    if media_lines:
        lines.extend(["", *media_lines])

    if tags:
        lines.extend(["", "标签：", str(tags).strip()])
    if post_url:
        lines.extend(["", "原帖：", post_url])
    return "\n".join(lines)


def send_to_feishu(*, webhook: str, text_content: str) -> None:
    feishu_post_json(
        webhook,
        {
            "msg_type": "text",
            "content": {"text": truncate_utf8(text_content, max_bytes=18000)},
        },
    )


def resolve_push_target(
    target: str,
    *,
    wework_webhook: str,
    feishu_webhook: str,
    has_feishu_app: bool = False,
) -> str:
    value = str(target or "auto").strip().lower()
    if value not in {"auto", "wework", "feishu", "both"}:
        raise ValueError("push target 必须是 auto/wework/feishu/both")

    has_wework = bool(str(wework_webhook or "").strip())
    has_feishu = bool(str(feishu_webhook or "").strip()) or has_feishu_app

    if value == "auto":
        if has_feishu:
            return "feishu"
        if has_wework:
            return "wework"
        raise ValueError(
            "auto 模式下未找到可用推送目标（需配置 FEISHU_WEBHOOK_URL、飞书应用机器人收件人，或 WEWORK_WEBHOOK_URL）"
        )

    if value == "wework" and not has_wework:
        raise ValueError("push_target=wework 但 WEWORK_WEBHOOK_URL 为空")
    if value == "feishu" and not has_feishu:
        raise ValueError("push_target=feishu 但既没有 FEISHU_WEBHOOK_URL，也没有可用的飞书应用机器人收件人")
    if value == "both" and (not has_wework or not has_feishu):
        raise ValueError("push_target=both 需要企业微信通道，以及飞书 webhook 或飞书应用机器人收件人")
    return value


def send_to_wework(
    *,
    webhook: str,
    text_content: str,
    image_bytes: Optional[bytes],
    post_url: str,
    video_title: str,
    video_desc: str,
    video_has_media: bool,
) -> None:
    wework_post_json(webhook, {"msgtype": "text", "text": {"content": text_content}})
    if image_bytes:
        wework_post_json(
            webhook,
            {
                "msgtype": "image",
                "image": {
                    "base64": base64.b64encode(image_bytes).decode("utf-8"),
                    "md5": hashlib.md5(image_bytes).hexdigest(),
                },
            },
        )
    if video_has_media:
        wework_post_json(
            webhook,
            {
                "msgtype": "news",
                "news": {
                    "articles": [
                        {
                            "title": f"🎬 视频帖｜{video_title[:70]}",
                            "description": video_desc[:200] or "点击查看原帖视频",
                            "url": post_url,
                        }
                    ]
                },
            },
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="按需查询 X 某账号最新帖子，并可推送到企业微信/飞书。"
    )
    parser.add_argument("username", help="X 用户名，可带 @，如 @realDonaldTrump")
    parser.add_argument(
        "--rss-base",
        default="http://127.0.0.1:1200",
        help="本地 RSSHub 地址，默认 http://127.0.0.1:1200",
    )
    parser.add_argument("--no-push", action="store_true", help="只在终端打印，不推送到微信")
    parser.add_argument(
        "--webhook-url",
        "--wework-webhook-url",
        dest="wework_webhook_url",
        default="",
        help="企业微信 webhook，默认读取 .env",
    )
    parser.add_argument(
        "--feishu-webhook-url",
        default="",
        help="飞书 webhook，默认读取 .env",
    )
    parser.add_argument(
        "--push-target",
        choices=["auto", "wework", "feishu", "both"],
        default="auto",
        help="推送目标，默认 auto（优先飞书，其次企业微信）",
    )
    parser.add_argument(
        "--no-translate", action="store_true", help="关闭中文翻译与总结，输出原文"
    )
    parser.add_argument("--with-ocr", action="store_true", help="启用图片 OCR（需安装 paddleocr）")
    parser.add_argument(
        "--with-asr",
        action="store_true",
        help="启用视频语音转写（需安装 faster-whisper + ffmpeg）",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    username = args.username.strip().lstrip("@")
    if not username:
        print("用户名不能为空", file=sys.stderr)
        return 2

    env = load_env_file(ENV_PATH)
    wework_webhook = args.wework_webhook_url or env.get("WEWORK_WEBHOOK_URL", "").strip()
    feishu_webhook = args.feishu_webhook_url or env.get("FEISHU_WEBHOOK_URL", "").strip()
    feishu_app_id = env.get("FEISHU_APP_ID", "").strip()
    feishu_app_secret = env.get("FEISHU_APP_SECRET", "").strip()
    feishu_recipients_file = resolve_recipients_file(env.get("FEISHU_APP_RECIPIENTS_FILE", ""))
    ai_base = normalize_ai_base(env.get("AI_API_BASE", ""))
    ai_model = strip_openai_prefix(env.get("AI_MODEL", "qwen2.5:1.5b"))
    ai_key = env.get("AI_API_KEY", "local_dummy_key")

    post: Optional[PostItem] = None
    try:
        post = fetch_from_rsshub(args.rss_base, username=username)
    except Exception as exc:
        print(f"[WARN] RSSHub 查询失败: {exc}", file=sys.stderr)

    if post is None:
        try:
            post = fetch_from_nitter(username=username)
            if post:
                print("[INFO] 使用 Nitter RSS 回退。", file=sys.stderr)
        except Exception as exc:
            print(f"[WARN] Nitter 回退失败: {exc}", file=sys.stderr)

    if post is None:
        db_path = resolve_rss_db_path()
        post = fetch_from_local_sqlite(db_path, username=username) if db_path else None
        if post:
            print("[INFO] 使用本地 SQLite 历史数据回退。", file=sys.stderr)

    if post is None:
        print(
            f"[ERROR] 未找到 @{username} 的帖子。请先确认账号存在，或让 RSSHub 能访问该账号。",
            file=sys.stderr,
        )
        return 1

    original_title = post.title or "[无标题帖子]"
    original_body = post.body_text or ""
    translated_title = ""
    translated_body = ""
    summary = ""
    tags = ""

    meaningful = has_meaningful_text(f"{original_title}\n{original_body}")
    if not meaningful:
        if post.video_urls:
            summary = "该帖子主要为视频内容，建议点开原帖查看完整视频。"
            tags = "#视频 #媒体帖"
        elif post.image_urls:
            summary = "该帖子主要为图片内容，建议查看配图与原帖。"
            tags = "#图片 #媒体帖"
        else:
            summary = "该帖可解析文本不足，建议直接查看原帖。"
            tags = "#X动态"
        original_body = original_body or "（未提取到可用正文文本）"
    elif not args.no_translate:
        try:
            title_cn = maybe_zh_translate(
                source_text=original_title, api_base=ai_base, model=ai_model, api_key=ai_key
            )
            body_cn = maybe_zh_translate(
                source_text=original_body, api_base=ai_base, model=ai_model, api_key=ai_key
            )
            summary = summarize_cn(
                title_cn=title_cn,
                body_cn=body_cn,
                api_base=ai_base,
                model=ai_model,
                api_key=ai_key,
            )
            tags = tags_cn(
                title_cn=title_cn,
                body_cn=body_cn,
                api_base=ai_base,
                model=ai_model,
                api_key=ai_key,
            )
            translated_title = title_cn or ""
            translated_body = body_cn or ""
        except Exception as exc:
            print(f"[WARN] 本地翻译失败，回退原文: {exc}", file=sys.stderr)

    image_bytes: Optional[bytes] = None
    ocr_text = ""
    if post.image_urls:
        try:
            image_bytes = download_bytes(post.image_urls[0])
            if args.with_ocr and image_bytes:
                with tempfile.NamedTemporaryFile(prefix="xradar_ocr_", suffix=".jpg", delete=False) as fp:
                    fp.write(image_bytes)
                    temp_path = Path(fp.name)
                try:
                    ocr_raw = ocr_with_paddle(temp_path)
                    if ocr_raw:
                        ocr_text = ocr_raw[:300]
                finally:
                    temp_path.unlink(missing_ok=True)
        except Exception as exc:
            print(f"[WARN] 图片下载/OCR失败: {exc}", file=sys.stderr)

    asr_text = ""
    if args.with_asr and post.video_urls:
        try:
            video_bytes = download_bytes(post.video_urls[0], timeout=60)
            with tempfile.NamedTemporaryFile(prefix="xradar_asr_", suffix=".mp4", delete=False) as fp:
                fp.write(video_bytes)
                video_path = Path(fp.name)
            try:
                asr_raw = transcribe_video_with_faster_whisper(video_path)
                if asr_raw:
                    asr_text = asr_raw[:500]
            finally:
                video_path.unlink(missing_ok=True)
        except Exception as exc:
            print(f"[WARN] 视频下载/ASR失败: {exc}", file=sys.stderr)

    text_content = build_post_message_text(
        header=f"【按需查询｜@{username} 最新帖子】",
        author_line=post.source_name,
        published_at=post.published_at,
        original_title=original_title,
        translated_title=translated_title,
        summary=summary,
        tags=tags,
        original_body=original_body,
        translated_body=translated_body,
        image_urls=post.image_urls,
        video_urls=post.video_urls,
        ocr_text=ocr_text,
        asr_text=asr_text,
        post_url=post.url,
        body_limit=800,
    )
    print(textwrap.shorten(text_content, width=1200, placeholder=" ..."))

    if args.no_push:
        return 0

    try:
        push_target = resolve_push_target(
            args.push_target,
            wework_webhook=wework_webhook,
            feishu_webhook=feishu_webhook,
            has_feishu_app=has_feishu_app_push_target(
                feishu_app_id,
                feishu_app_secret,
                feishu_recipients_file,
            ),
        )
    except ValueError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2

    pushed_to: List[str] = []
    try:
        if push_target in {"wework", "both"}:
            send_to_wework(
                webhook=wework_webhook,
                text_content=text_content,
                image_bytes=image_bytes,
                post_url=post.url,
                video_title=translated_title or original_title,
                video_desc=summary or translated_body[:120] or original_body[:120],
                video_has_media=bool(post.video_urls),
            )
            pushed_to.append("企业微信")
        if push_target in {"feishu", "both"}:
            if feishu_webhook:
                send_to_feishu(webhook=feishu_webhook, text_content=text_content)
                pushed_to.append("飞书Webhook")
            else:
                sent_count, _ = send_text_to_recipients(
                    app_id=feishu_app_id,
                    app_secret=feishu_app_secret,
                    recipients_file=feishu_recipients_file,
                    text=text_content,
                )
                if sent_count <= 0:
                    raise RuntimeError("飞书应用机器人没有可用收件人，请先私聊机器人一次")
                pushed_to.append(f"飞书应用机器人({sent_count})")
    except Exception as exc:
        print(f"[ERROR] 推送失败: {exc}", file=sys.stderr)
        return 1

    print(f"[OK] 已推送到：{', '.join(pushed_to)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
