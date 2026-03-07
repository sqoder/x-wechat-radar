import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from feishu_command_bot import extract_username, normalize_command_text  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
