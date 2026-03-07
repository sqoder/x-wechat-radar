import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from x_latest_post import (  # noqa: E402
    _to_x_status_url_from_nitter,
    extract_media_urls,
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

    def test_resolve_push_target_both_requires_two_webhooks(self):
        with self.assertRaises(ValueError):
            resolve_push_target(
                "both",
                wework_webhook="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=demo",
                feishu_webhook="",
            )


if __name__ == "__main__":
    unittest.main()
