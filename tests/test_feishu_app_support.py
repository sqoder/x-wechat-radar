import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from feishu_app_support import (  # noqa: E402
    list_active_recipients,
    resolve_data_path,
    upsert_p2p_recipient,
)


class TestFeishuAppSupport(unittest.TestCase):
    def test_upsert_p2p_recipient_add_and_update(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "recipients.json"

            added = upsert_p2p_recipient(
                path,
                chat_id="oc_test_chat",
                open_id="ou_test_open",
                user_id="u_test_user",
                source="message",
            )
            self.assertTrue(added)

            recipients = list_active_recipients(path)
            self.assertEqual(len(recipients), 1)
            self.assertEqual(recipients[0]["chat_id"], "oc_test_chat")
            self.assertEqual(recipients[0]["open_id"], "ou_test_open")

            added_again = upsert_p2p_recipient(
                path,
                chat_id="oc_test_chat",
                open_id="ou_new_open",
                source="p2p_entered",
            )
            self.assertFalse(added_again)

            recipients = list_active_recipients(path)
            self.assertEqual(len(recipients), 1)
            self.assertEqual(recipients[0]["open_id"], "ou_new_open")

    def test_resolve_data_path_relative_to_repo_root(self):
        default_path = ROOT / "output" / "demo.json"
        resolved = resolve_data_path("output/custom.json", default_path)
        self.assertEqual(resolved, ROOT / "output" / "custom.json")


if __name__ == "__main__":
    unittest.main()
