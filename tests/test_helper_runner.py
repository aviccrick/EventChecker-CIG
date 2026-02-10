import unittest
from pathlib import Path


class TestHelperRunner(unittest.TestCase):
    def test_build_command_uses_venv_python(self):
        from helper_runner import build_run_command

        cmd = build_run_command(Path("/tmp/repo"))
        self.assertEqual(cmd[0], "/tmp/repo/.venv/bin/python3")
        self.assertEqual(cmd[1], "/tmp/repo/checker.py")


if __name__ == "__main__":
    unittest.main()
