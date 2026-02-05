import unittest


class TestHelperUI(unittest.TestCase):
    def test_index_html_contains_controls(self):
        from helper_ui import render_index_html

        html = render_index_html()
        self.assertIn("Run now", html)
        self.assertIn("Pause scheduling", html)
        self.assertIn("Stop helper", html)


if __name__ == "__main__":
    unittest.main()
