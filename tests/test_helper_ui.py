import unittest


class TestHelperUI(unittest.TestCase):
    def test_toolbar_html_contains_controls(self):
        from helper_ui import build_toolbar_html

        html = build_toolbar_html()
        self.assertIn("Run now", html)
        self.assertIn("Pause scheduling", html)
        self.assertIn("Stop helper", html)

    def test_inject_toolbar_inserts_controls_and_script(self):
        from helper_ui import inject_toolbar

        report_html = """
        <html>
          <body>
            <nav class=\"navbar\">Nav</nav>
            <div class=\"max-w-7xl mx-auto p-4 md:p-8\">Report Body</div>
          </body>
        </html>
        """
        combined = inject_toolbar(report_html)
        self.assertIn("id=\"helper-controls\"", combined)
        self.assertIn("id=\"helper-script\"", combined)

    def test_inject_toolbar_does_not_use_iframe(self):
        from helper_ui import inject_toolbar

        report_html = "<html><body>Report Body</body></html>"
        combined = inject_toolbar(report_html)
        self.assertNotIn("<iframe", combined)


if __name__ == "__main__":
    unittest.main()
