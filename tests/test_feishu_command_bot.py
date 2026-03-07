import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from feishu_command_bot import (  # noqa: E402
    BotConfig,
    build_reply_text,
    extract_username,
    normalize_command_text,
    select_pending_posts,
)
from x_latest_post import PostItem  # noqa: E402


class TestFeishuCommandParser(unittest.TestCase):
    def test_extract_alias_cn(self):
        self.assertEqual(extract_username("我要看马斯克最新帖子"), "elonmusk")

    def test_extract_at_username(self):
        self.assertEqual(extract_username("查看 @realDonaldTrump 最新推特"), "realDonaldTrump")

    def test_extract_plain_query(self):
        self.assertEqual(extract_username("查 gdb 最新帖子"), "gdb")

    def test_extract_not_found(self):
        self.assertIsNone(extract_username("今天天气怎么样"))

    def test_extract_with_lark_at_tag(self):
        text = '<at user_id="ou_xxx">11</at> 查看 openai 最新动态'
        self.assertEqual(extract_username(text), "OpenAI")

    def test_normalize_command_text_removes_mentions(self):
        text = '<at user_id="ou_xxx">11</at>  我要看 @realDonaldTrump 最新推特'
        normalized = normalize_command_text(text)
        self.assertNotIn("<at", normalized)
        self.assertEqual(normalized, "我要看 @realDonaldTrump 最新推特")

    def test_select_pending_posts_skips_sent_and_dedupes_duplicates(self):
        posts = [
            PostItem(
                username="openai",
                source_name="@openai",
                title="Latest release",
                url="https://x.com/openai/status/2",
                published_at="2026-03-08T00:02:00Z",
                body_text="release body",
                image_urls=[],
                video_urls=[],
                source="rsshub",
            ),
            PostItem(
                username="openai",
                source_name="@openai",
                title="Latest release duplicate",
                url="https://x.com/openai/status/2",
                published_at="2026-03-08T00:02:00Z",
                body_text="release body duplicate",
                image_urls=[],
                video_urls=[],
                source="rss-db",
            ),
            PostItem(
                username="openai",
                source_name="@openai",
                title="Earlier release",
                url="https://x.com/openai/status/1",
                published_at="2026-03-08T00:01:00Z",
                body_text="earlier body",
                image_urls=[],
                video_urls=[],
                source="rsshub",
            ),
        ]

        pending = select_pending_posts(posts, {"https://x.com/openai/status/1"})

        self.assertEqual([item.url for item in pending], ["https://x.com/openai/status/2"])

    @patch("feishu_command_bot.tags_cn", return_value="#特朗普 #马斯克")
    @patch("feishu_command_bot.summarize_cn", return_value="这是中文总结。")
    @patch("feishu_command_bot.maybe_zh_translate", side_effect=["美国党", "这是中文翻译正文。"])
    def test_build_reply_text_uses_feishu_layout(
        self,
        _mock_translate,
        _mock_summary,
        _mock_tags,
    ):
        cfg = BotConfig(
            app_id="app",
            app_secret="secret",
            rss_base="http://127.0.0.1:1200",
            enable_translate=True,
            ai_base="http://127.0.0.1:11434/v1",
            ai_model="qwen2.5:1.5b",
            ai_key="local_dummy_key",
            recipients_file=Path("output/feishu_app_recipients.json"),
            proactive_push_enabled=True,
            proactive_push_poll_seconds=60,
            proactive_push_fetch_limit=200,
            proactive_push_daily_time="08:00",
            proactive_push_daily_max_items=20,
            proactive_push_bootstrap_skip_existing=True,
            proactive_push_state_file=Path("output/feishu_app_push_state.json"),
            proactive_push_state_max_urls=5000,
        )
        post = PostItem(
            username="elonmusk",
            source_name="@elonmusk",
            title="America Party",
            url="https://x.com/elonmusk/status/123",
            published_at="2026-03-08T00:01:02Z",
            body_text="This is the original body.",
            image_urls=["https://img.example/a.jpg"],
            video_urls=[],
            source="nitter",
        )

        text = build_reply_text(post, cfg)

        self.assertTrue(text.startswith("🧠 美国党"))
        self.assertIn("@elonmusk | 2026-03-08 08:01:02", text)
        self.assertIn("核心内容：", text)
        self.assertIn("原文：This is the original body.", text)
        self.assertIn("翻译：这是中文翻译正文。", text)
        self.assertIn("总结：这是中文总结。", text)
        self.assertIn("标签：\n#特朗普 #马斯克", text)
        self.assertIn("原帖：\nhttps://x.com/elonmusk/status/123", text)


if __name__ == "__main__":
    unittest.main()
