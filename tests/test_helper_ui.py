import unittest


class TestHelperUI(unittest.TestCase):
    def test_index_html_contains_controls(self):
        from helper_ui import render_index_html

        html = render_index_html()
        self.assertIn("Run now", html)
        self.assertIn("Pause scheduling", html)
        self.assertIn("Stop helper", html)

    def test_index_html_matches_report_style(self):
        from helper_ui import render_index_html

        html = render_index_html()
        self.assertIn("cdn.jsdelivr.net/npm/daisyui", html)
        self.assertIn("cdn.tailwindcss.com", html)
        self.assertIn("fonts.googleapis.com/css2?family=Space+Grotesk", html)
        self.assertIn("class=\"navbar", html)


if __name__ == "__main__":
    unittest.main()
