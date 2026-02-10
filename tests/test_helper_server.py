import unittest
from datetime import datetime, timezone
import socket


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

    def test_build_servers_includes_ipv4_and_ipv6_when_available(self):
        from helper import build_servers

        class DummyServer:
            address_family = socket.AF_INET

            def __init__(self, server_address, handler_class):
                self.server_address = server_address

            def server_close(self):
                return None

        class DummyIPv6Server(DummyServer):
            address_family = socket.AF_INET6

        servers = build_servers(
            port=0,
            server_factory=DummyServer,
            ipv6_server_factory=DummyIPv6Server,
            ipv6_enabled=True,
        )
        try:
            self.assertTrue(
                any(server.address_family == socket.AF_INET for server in servers)
            )
            self.assertTrue(
                any(server.address_family == socket.AF_INET6 for server in servers)
            )
        finally:
            for server in servers:
                server.server_close()


if __name__ == "__main__":
    unittest.main()
