import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from x_latest_post import (  # noqa: E402
    _to_x_status_url_from_nitter,
    build_post_message_text,
    extract_media_urls,
    format_china_time,
    has_meaningful_text,
    normalize_ai_base,
    resolve_push_target,
)


class TestXLatestHelpers(unittest.TestCase):
    def test_has_meaningful_text_false_for_media_only(self):
        self.assertFalse(has_meaningful_text("Video"))
        self.assertFalse(has_meaningful_text("photo"))

    def test_has_meaningful_text_true_for_sentence(self):
        self.assertTrue(
            has_meaningful_text(
                "GPT-5.4 is very strong at productivity tasks with excel and word."
            )
        )

    def test_convert_nitter_link_to_x_status(self):
        url = "https://nitter.net/elonmusk/status/2030176168989839815#m"
        self.assertEqual(
            _to_x_status_url_from_nitter(url, "elonmusk"),
            "https://x.com/elonmusk/status/2030176168989839815",
        )

    def test_extract_media_urls(self):
        html = """
            <p>hello</p>
            <img src="https://img.example/a.jpg" />
            <video src="https://video.example/v.mp4"></video>
            <img src="https://img.example/a.jpg" />
        """
        media = extract_media_urls(html)
        self.assertEqual(media["image"], ["https://img.example/a.jpg"])
        self.assertEqual(media["video"], ["https://video.example/v.mp4"])

    def test_build_post_message_text_uses_feishu_layout(self):
        text = build_post_message_text(
            header="【按需查询｜@elonmusk 最新帖子】",
            author_line="Elon Musk / @elonmusk",
            published_at="2026-03-08T00:01:02Z",
            original_title="America Party",
            translated_title="美国党",
            summary="特朗普和马斯克继续谈论新政党。",
            tags="#特朗普 #马斯克",
            original_body="This is the original body.",
            translated_body="这是中文翻译内容。",
            image_urls=["https://img.example/a.jpg"],
            video_urls=["https://video.example/v.mp4"],
            post_url="https://x.com/elonmusk/status/123",
        )

        self.assertTrue(text.startswith("🧠 美国党"))
        self.assertIn("Elon Musk / @elonmusk | 2026-03-08 08:01:02", text)
        self.assertIn("核心内容：", text)
        self.assertIn("原文：This is the original body.", text)
        self.assertIn("翻译：这是中文翻译内容。", text)
        self.assertIn("总结：特朗普和马斯克继续谈论新政党。", text)
        self.assertIn("图片：https://img.example/a.jpg", text)
        self.assertIn("视频：https://video.example/v.mp4", text)
        self.assertIn("标签：\n#特朗普 #马斯克", text)
        self.assertIn("原帖：\nhttps://x.com/elonmusk/status/123", text)

    def test_build_post_message_text_marks_video_thumbnail_posts(self):
        text = build_post_message_text(
            header="【按需查询｜@realDonaldTrump 最新帖子】",
            author_line="Donald Trump / @realDonaldTrump",
            published_at="2026-03-08T00:01:02Z",
            original_title="Video",
            summary="该帖子主要为视频内容。",
            original_body="Video",
            image_urls=["https://nitter.net/pic/amplify_video_thumb/demo.jpg"],
            post_url="https://x.com/realDonaldTrump/status/123",
        )

        self.assertTrue(text.startswith("🧠 Video"))
        self.assertIn("图片：https://nitter.net/pic/amplify_video_thumb/demo.jpg", text)
        self.assertIn("视频：该帖为视频帖，当前源仅返回预览图，请点开原帖观看", text)

    def test_format_china_time_for_rfc822(self):
        self.assertEqual(
            format_china_time("Sat, 28 Feb 2026 07:44:23 GMT"),
            "2026-02-28 15:44:23",
        )

    def test_format_china_time_for_iso8601(self):
        self.assertEqual(
            format_china_time("2026-03-06T18:19:33Z"),
            "2026-03-07 02:19:33",
        )

    def test_normalize_ai_base_on_host_replaces_host_docker_internal(self):
        with patch.dict("os.environ", {"RUNNING_IN_DOCKER": "0"}):
            self.assertEqual(
                normalize_ai_base("http://host.docker.internal:11434/v1"),
                "http://127.0.0.1:11434/v1",
            )

    def test_normalize_ai_base_in_docker_keeps_host_docker_internal(self):
        with patch.dict("os.environ", {"RUNNING_IN_DOCKER": "1"}):
            self.assertEqual(
                normalize_ai_base("http://host.docker.internal:11434/v1"),
                "http://host.docker.internal:11434/v1",
            )

    def test_resolve_push_target_auto_prefers_feishu(self):
        self.assertEqual(
            resolve_push_target(
                "auto",
                wework_webhook="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=demo",
                feishu_webhook="https://open.feishu.cn/open-apis/bot/v2/hook/demo",
            ),
            "feishu",
        )

    def test_resolve_push_target_auto_fallback_to_wework(self):
        self.assertEqual(
            resolve_push_target(
                "auto",
                wework_webhook="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=demo",
                feishu_webhook="",
            ),
            "wework",
        )

    def test_resolve_push_target_auto_accepts_feishu_app(self):
        self.assertEqual(
            resolve_push_target(
                "auto",
                wework_webhook="",
                feishu_webhook="",
                has_feishu_app=True,
            ),
            "feishu",
        )

    def test_resolve_push_target_both_requires_two_webhooks(self):
        with self.assertRaises(ValueError):
            resolve_push_target(
                "both",
                wework_webhook="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=demo",
                feishu_webhook="",
            )


if __name__ == "__main__":
    unittest.main()
