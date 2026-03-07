#!/usr/bin/env python3
"""
把主配置中的 RSS feeds 按轮询分片，生成多个配置目录。

用途：
- 降低单实例每轮抓取压力
- 配合 docker-compose 的 sharded profile 做错峰抓取
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
BASE_CONFIG = ROOT / "config" / "config.yaml"
OUTPUT_ROOT = ROOT / "generated-configs" / "shards"

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
        die("Cannot find rss.feeds start marker in config/config.yaml")
    start += len(FEEDS_START)

    end = config_text.find(FEEDS_END, start)
    if end < 0:
        die("Cannot find report section marker after rss.feeds in config/config.yaml")

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
            }
        )
    if not feeds:
        die("No feeds found in config/config.yaml")
    return start, end, feeds


def build_config_text(base_text: str, feeds_start: int, feeds_end: int, feeds: list) -> str:
    blocks = []
    for f in feeds:
        blocks.append(
            f'    - id: "{f["id"]}"\n'
            f'      name: "{f["name"]}"\n'
            f'      url: "{f["url"]}"'
        )
    body = "\n\n".join(blocks).rstrip() + "\n\n"
    return base_text[:feeds_start] + body + base_text[feeds_end:]


def main() -> None:
    parser = argparse.ArgumentParser(description="Build sharded RSS configs")
    parser.add_argument("--shards", type=int, default=3, help="Number of shards (default: 3)")
    args = parser.parse_args()

    shard_count = max(1, args.shards)
    if not BASE_CONFIG.exists():
        die("Missing config/config.yaml")

    base_text = BASE_CONFIG.read_text(encoding="utf-8")
    feeds_start, feeds_end, feeds = parse_master_feeds(base_text)

    shards = [[] for _ in range(shard_count)]
    for idx, feed in enumerate(feeds):
        shards[idx % shard_count].append(feed)

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    for i in range(shard_count):
        out_dir = OUTPUT_ROOT / f"shard{i+1}"
        out_dir.mkdir(parents=True, exist_ok=True)
        for file_name in SHARED_FILES:
            src = ROOT / "config" / file_name
            shutil.copy2(src, out_dir / file_name)
        out_cfg = out_dir / "config.yaml"
        out_cfg.write_text(
            build_config_text(base_text, feeds_start, feeds_end, shards[i]),
            encoding="utf-8",
        )
        print(f"[OK] shard{i+1}: {len(shards[i])} feeds -> {out_cfg}")

    print(f"[INFO] total feeds: {len(feeds)}, shards: {shard_count}")


if __name__ == "__main__":
    main()

