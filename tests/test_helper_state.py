import unittest
from datetime import datetime, timedelta, timezone


class TestHelperState(unittest.TestCase):
    def test_default_config_values(self):
        from helper_state import load_config

        cfg = load_config("/tmp/nonexistent-config.json")
        self.assertEqual(cfg["interval_minutes"], 360)
        self.assertFalse(cfg["paused"])

    def test_compute_next_run_paused(self):
        from helper_state import compute_next_run

        now = datetime(2026, 2, 5, 12, 0, tzinfo=timezone.utc)
        self.assertIsNone(compute_next_run(now, 360, paused=True, last_run=None))

    def test_compute_next_run_from_last(self):
        from helper_state import compute_next_run

        now = datetime(2026, 2, 5, 12, 0, tzinfo=timezone.utc)
        last = now - timedelta(hours=1)
        nxt = compute_next_run(now, 360, paused=False, last_run=last)
        self.assertEqual(nxt, last + timedelta(minutes=360))


if __name__ == "__main__":
    unittest.main()
