import importlib.util
import sys
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SENDERS_PATH = ROOT / "overrides" / "trendradar" / "notification" / "senders.py"

# 为 senders.py 的相对导入提供最小桩模块
trendradar_pkg = types.ModuleType("trendradar")
notification_pkg = types.ModuleType("trendradar.notification")
batch_mod = types.ModuleType("trendradar.notification.batch")
formatters_mod = types.ModuleType("trendradar.notification.formatters")

batch_mod.add_batch_headers = lambda batches, *_args, **_kwargs: batches
batch_mod.get_max_batch_header_size = lambda *_args, **_kwargs: 0
formatters_mod.convert_markdown_to_mrkdwn = lambda text: text
formatters_mod.strip_markdown = lambda text: text

sys.modules["trendradar"] = trendradar_pkg
sys.modules["trendradar.notification"] = notification_pkg
sys.modules["trendradar.notification.batch"] = batch_mod
sys.modules["trendradar.notification.formatters"] = formatters_mod

spec = importlib.util.spec_from_file_location(
    "trendradar.notification.senders", SENDERS_PATH
)
senders_mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(senders_mod)


class TestMediaSummaryHelpers(unittest.TestCase):
    def test_extract_brief_from_summary(self):
        summary = "标签: #AI | 摘要: OpenAI released Codex Security. | 图片: https://img.example/a.jpg"
        brief = senders_mod._extract_brief_from_summary(summary)
        self.assertEqual(brief, "OpenAI released Codex Security.")

    def test_append_media_summary(self):
        entry = {
            "summary": "标签: #AI | 摘要: test content | 图片: https://img.example/a.jpg"
        }
        senders_mod._append_media_summary(entry, "这是一张产品发布会现场图。")
        self.assertIn("媒体总结:", entry["summary"])
        self.assertIn("这是一张产品发布会现场图。", entry["summary"])

    def test_build_media_cache_key_stable(self):
        entry = {"url": "https://x.com/OpenAI/status/12345"}
        key1 = senders_mod._build_media_cache_key(
            entry, "https://img.example/a.jpg", "gemini-2.5-flash"
        )
        key2 = senders_mod._build_media_cache_key(
            entry, "https://img.example/a.jpg", "gemini-2.5-flash"
        )
        self.assertEqual(key1, key2)


if __name__ == "__main__":
    unittest.main()
