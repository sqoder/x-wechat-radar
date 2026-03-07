#!/usr/bin/env python3
# coding: utf-8

from __future__ import annotations

import json
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_RECIPIENTS_FILE = ROOT_DIR / "output" / "feishu_app_recipients.json"
_REGISTRY_LOCK = threading.Lock()
_TOKEN_CACHE: Dict[str, Dict[str, object]] = {}


def parse_bool(value: str, default: bool = False) -> bool:
    text = str(value or "").strip().lower()
    if not text:
        return default
    return text in {"1", "true", "yes", "y", "on"}


def resolve_data_path(raw_path: str, default_path: Path) -> Path:
    text = str(raw_path or "").strip()
    if not text:
        return default_path
    path = Path(text)
    if path.is_absolute():
        return path
    return ROOT_DIR / path


def resolve_recipients_file(raw_path: str = "") -> Path:
    return resolve_data_path(raw_path, DEFAULT_RECIPIENTS_FILE)


def _default_registry() -> Dict[str, object]:
    return {"version": 1, "recipients": []}


def load_recipient_registry(path: Path) -> Dict[str, object]:
    if not path.exists():
        return _default_registry()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return _default_registry()
    if not isinstance(data, dict):
        return _default_registry()
    recipients = data.get("recipients")
    if not isinstance(recipients, list):
        data["recipients"] = []
    return data


def save_recipient_registry(path: Path, data: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def upsert_p2p_recipient(
    path: Path,
    *,
    chat_id: str,
    open_id: str = "",
    user_id: str = "",
    tenant_key: str = "",
    source: str = "",
) -> bool:
    chat_value = str(chat_id or "").strip()
    open_value = str(open_id or "").strip()
    user_value = str(user_id or "").strip()
    if not chat_value and not open_value and not user_value:
        return False

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with _REGISTRY_LOCK:
        data = load_recipient_registry(path)
        recipients = data.setdefault("recipients", [])
        if not isinstance(recipients, list):
            recipients = []
            data["recipients"] = recipients

        for recipient in recipients:
            if not isinstance(recipient, dict):
                continue
            if chat_value and recipient.get("chat_id") == chat_value:
                recipient.update(
                    {
                        "chat_id": chat_value,
                        "open_id": open_value or recipient.get("open_id", ""),
                        "user_id": user_value or recipient.get("user_id", ""),
                        "tenant_key": tenant_key or recipient.get("tenant_key", ""),
                        "source": source or recipient.get("source", ""),
                        "active": True,
                        "updated_at": now,
                    }
                )
                save_recipient_registry(path, data)
                return False

        recipients.append(
            {
                "chat_id": chat_value,
                "open_id": open_value,
                "user_id": user_value,
                "tenant_key": tenant_key,
                "source": source,
                "active": True,
                "updated_at": now,
            }
        )
        save_recipient_registry(path, data)
        return True


def list_active_recipients(path: Path) -> List[Dict[str, str]]:
    data = load_recipient_registry(path)
    recipients = data.get("recipients", [])
    result: List[Dict[str, str]] = []
    if not isinstance(recipients, list):
        return result
    for item in recipients:
        if not isinstance(item, dict):
            continue
        if item.get("active") is False:
            continue
        chat_id = str(item.get("chat_id", "") or "").strip()
        open_id = str(item.get("open_id", "") or "").strip()
        user_id = str(item.get("user_id", "") or "").strip()
        if not chat_id and not open_id and not user_id:
            continue
        result.append(
            {
                "chat_id": chat_id,
                "open_id": open_id,
                "user_id": user_id,
                "tenant_key": str(item.get("tenant_key", "") or "").strip(),
                "source": str(item.get("source", "") or "").strip(),
            }
        )
    return result


def _truncate_text(text: str, max_bytes: int = 14000) -> str:
    raw = str(text or "").encode("utf-8")
    if len(raw) <= max_bytes:
        return str(text or "")
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


def get_tenant_access_token(app_id: str, app_secret: str, *, timeout: int = 20) -> str:
    app_id_value = str(app_id or "").strip()
    app_secret_value = str(app_secret or "").strip()
    if not app_id_value or not app_secret_value:
        raise RuntimeError("缺少 FEISHU_APP_ID 或 FEISHU_APP_SECRET")

    cache_key = f"{app_id_value}:{app_secret_value}"
    now = time.time()
    cached = _TOKEN_CACHE.get(cache_key)
    if cached:
        expires_at = float(cached.get("expires_at", 0) or 0)
        token = str(cached.get("token", "") or "").strip()
        if token and expires_at - 60 > now:
            return token

    response = requests.post(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        json={"app_id": app_id_value, "app_secret": app_secret_value},
        timeout=timeout,
    )
    response.raise_for_status()
    data = response.json()
    if data.get("code") not in (0, None):
        raise RuntimeError(f"获取飞书 tenant_access_token 失败: {data}")

    token = str(data.get("tenant_access_token", "") or "").strip()
    if not token:
        raise RuntimeError(f"飞书 tenant_access_token 响应缺少 token: {data}")

    expire = int(data.get("expire", 7200) or 7200)
    _TOKEN_CACHE[cache_key] = {"token": token, "expires_at": now + expire}
    return token


def send_text_message(
    *,
    app_id: str,
    app_secret: str,
    receive_id: str,
    receive_id_type: str,
    text: str,
    timeout: int = 20,
) -> Dict[str, object]:
    token = get_tenant_access_token(app_id, app_secret, timeout=timeout)
    response = requests.post(
        f"https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type={receive_id_type}",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        },
        json={
            "receive_id": str(receive_id or "").strip(),
            "msg_type": "text",
            "content": json.dumps({"text": _truncate_text(text)}, ensure_ascii=False),
            "uuid": str(uuid.uuid4()),
        },
        timeout=timeout,
    )
    response.raise_for_status()
    data = response.json()
    if data.get("code") not in (0, None):
        raise RuntimeError(f"飞书应用机器人发消息失败: {data}")
    return data


def send_text_to_recipients(
    *,
    app_id: str,
    app_secret: str,
    recipients_file: Path,
    text: str,
    timeout: int = 20,
) -> Tuple[int, List[str]]:
    recipients = list_active_recipients(recipients_file)
    if not recipients:
        return 0, []

    success_count = 0
    delivered_to: List[str] = []
    for recipient in recipients:
        chat_id = str(recipient.get("chat_id", "") or "").strip()
        open_id = str(recipient.get("open_id", "") or "").strip()
        user_id = str(recipient.get("user_id", "") or "").strip()

        if chat_id:
            receive_id = chat_id
            receive_id_type = "chat_id"
        elif open_id:
            receive_id = open_id
            receive_id_type = "open_id"
        elif user_id:
            receive_id = user_id
            receive_id_type = "user_id"
        else:
            continue

        send_text_message(
            app_id=app_id,
            app_secret=app_secret,
            receive_id=receive_id,
            receive_id_type=receive_id_type,
            text=text,
            timeout=timeout,
        )
        success_count += 1
        delivered_to.append(receive_id)

    return success_count, delivered_to


def has_feishu_app_push_target(app_id: str, app_secret: str, recipients_file: Path) -> bool:
    if not str(app_id or "").strip() or not str(app_secret or "").strip():
        return False
    return bool(list_active_recipients(recipients_file))
