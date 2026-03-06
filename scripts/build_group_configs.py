#!/usr/bin/env python3
"""
Build grouped TrendRadar configs from:
- config/config.yaml (master feed list)
- config/feed_groups.json (handle grouping)

Output:
- generated-configs/ai/config.yaml
- generated-configs/politics/config.yaml
- generated-configs/invest/config.yaml
"""

from __future__ import annotations

import json
import re
import shutil
import sys
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
BASE_CONFIG = ROOT / "config" / "config.yaml"
GROUP_FILE = ROOT / "config" / "feed_groups.json"
OUTPUT_ROOT = ROOT / "generated-configs"

SHARED_FILES = [
    "timeline.yaml",
    "frequency_words.txt",
    "ai_analysis_prompt.txt",
    "ai_translation_prompt.txt",
]

FEEDS_START = "  feeds:\n"
FEEDS_END = "\n\n# ===============================================================\n# 4. 报告模式\n"


def die(msg: str) -> None:
    print(f"[ERROR] {msg}")
    sys.exit(1)


def parse_master_feeds(config_text: str):
    start = config_text.find(FEEDS_START)
    if start < 0:
        die("Cannot find `rss.feeds` start marker in config/config.yaml")
    start += len(FEEDS_START)

    end = config_text.find(FEEDS_END, start)
    if end < 0:
        die("Cannot find report section marker after `rss.feeds` in config/config.yaml")

    feeds_text = config_text[start:end]
    pattern = re.compile(
        r'^\s*-\s*id:\s*"(?P<id>[^"]+)"\s*$\n'
        r'^\s*name:\s*"(?P<name>[^"]+)"\s*$\n'
        r'^\s*url:\s*"(?P<url>http://rsshub:1200/twitter/user/(?P<handle>[^"]+))"\s*$',
        re.MULTILINE,
    )

    feeds = []
    for m in pattern.finditer(feeds_text):
        feeds.append(
            {
                "id": m.group("id"),
                "name": m.group("name"),
                "url": m.group("url"),
                "handle": m.group("handle"),
                "handle_lower": m.group("handle").lower(),
            }
        )

    if not feeds:
        die("No RSS feed entries found in config/config.yaml")

    by_handle = {}
    for f in feeds:
        k = f["handle_lower"]
        if k in by_handle:
            die(f"Duplicate handle found in master config: {f['handle']}")
        by_handle[k] = f

    return start, end, feeds, by_handle


def validate_group_file(group_data: dict):
    groups = group_data.get("groups")
    if not isinstance(groups, dict) or not groups:
        die("config/feed_groups.json must contain a non-empty `groups` object")

    overlaps = defaultdict(list)
    for group_name, group_cfg in groups.items():
        handles = group_cfg.get("handles", [])
        if not isinstance(handles, list):
            die(f"group `{group_name}` handles must be a list")

        handle_lower = [h.lower() for h in handles]
        dup = [k for k, v in Counter(handle_lower).items() if v > 1]
        if dup:
            die(f"group `{group_name}` has duplicate handles: {dup}")

        for h in handle_lower:
            overlaps[h].append(group_name)

    conflicted = {h: gs for h, gs in overlaps.items() if len(gs) > 1}
    if conflicted:
        print("[WARN] Cross-group overlaps detected:")
        for h, gs in sorted(conflicted.items()):
            print(f"  - @{h}: {', '.join(gs)}")

    return groups


def build_group_config_text(base_text: str, feeds_start: int, feeds_end: int, group_feeds: list) -> str:
    blocks = []
    for f in group_feeds:
        blocks.append(
            f'    - id: "{f["id"]}"\n'
            f'      name: "{f["name"]}"\n'
            f'      url: "{f["url"]}"'
        )

    body = "\n\n".join(blocks).rstrip() + "\n\n"
    return base_text[:feeds_start] + body + base_text[feeds_end:]


def main() -> None:
    if not BASE_CONFIG.exists():
        die("Missing config/config.yaml")
    if not GROUP_FILE.exists():
        die("Missing config/feed_groups.json")

    base_text = BASE_CONFIG.read_text(encoding="utf-8")
    feeds_start, feeds_end, all_feeds, by_handle = parse_master_feeds(base_text)

    group_data = json.loads(GROUP_FILE.read_text(encoding="utf-8"))
    groups = validate_group_file(group_data)

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)

    assigned_handles = set()

    for group_name, group_cfg in groups.items():
        group_handles = group_cfg.get("handles", [])
        missing = []
        selected = []

        for h in group_handles:
            key = h.lower()
            f = by_handle.get(key)
            if f is None:
                missing.append(h)
                continue
            selected.append(f)
            assigned_handles.add(key)

        if missing:
            print(f"[WARN] group `{group_name}` has {len(missing)} handles not found in master feeds:")
            for h in missing:
                print(f"  - @{h}")

        if not selected:
            die(f"group `{group_name}` has no matched feeds; please fix config/feed_groups.json")

        out_dir = OUTPUT_ROOT / group_name
        out_dir.mkdir(parents=True, exist_ok=True)

        for file_name in SHARED_FILES:
            src = ROOT / "config" / file_name
            dst = out_dir / file_name
            shutil.copy2(src, dst)

        out_config = out_dir / "config.yaml"
        out_config.write_text(
            build_group_config_text(base_text, feeds_start, feeds_end, selected),
            encoding="utf-8",
        )

        print(f"[OK] {group_name}: {len(selected)} feeds -> {out_config}")

    unassigned = [f["handle"] for f in all_feeds if f["handle_lower"] not in assigned_handles]
    print(f"[INFO] master feeds: {len(all_feeds)}")
    print(f"[INFO] assigned to groups: {len(assigned_handles)}")
    print(f"[INFO] unassigned: {len(unassigned)}")
    if unassigned:
        print("[INFO] first unassigned handles:")
        for h in unassigned[:20]:
            print(f"  - @{h}")


if __name__ == "__main__":
    main()
