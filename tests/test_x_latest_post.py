import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from x_latest_post import (  # noqa: E402
    _to_x_status_url_from_nitter,
    extract_media_urls,
    has_meaningful_text,
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


if __name__ == "__main__":
    unittest.main()

