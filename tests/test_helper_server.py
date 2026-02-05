import unittest
from datetime import datetime, timezone


class TestHelperServer(unittest.TestCase):
    def test_status_payload_includes_fields(self):
        from helper_state import HelperState
        from helper import build_status_payload

        state = HelperState(running=False, paused=True)
        payload = build_status_payload(state)
        self.assertIn("state", payload)
        self.assertIn("paused", payload)
        self.assertIn("last_run", payload)
        self.assertIn("next_run", payload)

    def test_iso_formatting(self):
        from helper import isoformat_or_none

        dt = datetime(2026, 2, 5, 12, 0, tzinfo=timezone.utc)
        self.assertEqual(isoformat_or_none(dt), "2026-02-05T12:00:00+00:00")


if __name__ == "__main__":
    unittest.main()
