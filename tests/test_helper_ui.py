import unittest


class TestHelperUI(unittest.TestCase):
    def test_toolbar_html_contains_controls(self):
        from helper_ui import build_toolbar_html

        html = build_toolbar_html()
        self.assertIn("Generate Report", html)
        self.assertIn("Pause Scheduled Runs", html)
        self.assertIn("Stop App", html)
        self.assertIn("Report & Schedule", html)

    def test_inject_toolbar_inserts_controls_and_script(self):
        from helper_ui import inject_toolbar

        report_html = """
        <html>
          <body>
            <nav class=\"navbar\">Nav</nav>
            <div class=\"max-w-7xl mx-auto px-2.5 py-4 md:py-8\">Report Body</div>
          </body>
        </html>
        """
        combined = inject_toolbar(report_html)
        self.assertIn("id=\"helper-controls\"", combined)
        self.assertIn("id=\"helper-script\"", combined)

    def test_inject_toolbar_replaces_spreadsheet_box(self):
        from helper_ui import inject_toolbar

        report_html = """
        <html><body>
          <div class=\"stat-box bg-white p-4 rounded-lg shadow-sm border border-slate-100\">
            <div class=\"text-xs uppercase font-bold text-slate-400\">Spreadsheet Data</div>
            <div class=\"text-lg font-medium\">Refreshed 5th Feb at 16:00</div>
            <div class=\"text-xs text-slate-500 mt-1\">Next update in 2 hr</div>
          </div>
        </body></html>
        """
        combined = inject_toolbar(report_html)
        self.assertIn("Next Scheduled Run", combined)
        self.assertIn("id=\"helper-next-run\"", combined)

    def test_inject_toolbar_adds_column_gap(self):
        from helper_ui import inject_toolbar

        report_html = """
        <html><body>
          <div class=\"grid gap-6 lg:grid-cols-[460px_minmax(0,1fr)]\">
            <aside>Left</aside>
            <main>Right</main>
          </div>
        </body></html>
        """
        combined = inject_toolbar(report_html)
        self.assertIn("grid gap-8 lg:grid-cols-[460px_minmax(0,1fr)]", combined)

    def test_inject_toolbar_does_not_use_iframe(self):
        from helper_ui import inject_toolbar

        report_html = "<html><body>Report Body</body></html>"
        combined = inject_toolbar(report_html)
        self.assertNotIn("<iframe", combined)


if __name__ == "__main__":
    unittest.main()
