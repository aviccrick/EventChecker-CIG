import sys
import types
import unittest


def _ensure_stub(module_name: str, **attrs: object) -> None:
    if module_name in sys.modules:
        return
    stub = types.ModuleType(module_name)
    for key, value in attrs.items():
        setattr(stub, key, value)
    sys.modules[module_name] = stub


try:
    import requests  # noqa: F401
except Exception:
    _ensure_stub("requests")

try:
    from bs4 import BeautifulSoup  # noqa: F401
except Exception:
    _ensure_stub("bs4", BeautifulSoup=object)

try:
    from playwright.sync_api import sync_playwright, TimeoutError  # noqa: F401
except Exception:
    _ensure_stub("playwright")
    _ensure_stub(
        "playwright.sync_api",
        sync_playwright=lambda: None,
        TimeoutError=Exception,
    )

from checker import render_report_html


class TestReportLayout(unittest.TestCase):
    def test_report_has_horizontal_gutter(self):
        report = {
            "generated_friendly": "Now",
            "sourceLastUpdatedFriendly": "Now",
            "nextUpdateMsg": "",
            "nextUpdateDue": True,
            "nextUpdateTargetEpoch": None,
            "priority": [],
            "groups": [],
        }
        html = render_report_html(report)
        self.assertIn(
            'class="max-w-7xl mx-auto px-2.5 py-4 md:py-8"',
            html,
        )


if __name__ == "__main__":
    unittest.main()
