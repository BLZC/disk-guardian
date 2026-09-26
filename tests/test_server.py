from __future__ import annotations

import http.client
import json
import sys
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import server  # noqa: E402


EXTENSION_ORIGIN = (
    "chrome-extension://ccpomkognonnccbjmiapheoadpnepnde"
)
STORE_EXTENSION_ORIGIN = (
    "chrome-extension://knfhjpciofoakljbmneaaailglnmamlk"
)


class ExtensionProjectionTests(unittest.TestCase):
    def test_extension_status_exposes_explicit_cleanup_state(self) -> None:
        complete = {
            "timestamp": "2026-09-26T12:00:00+08:00",
            "disk": {
                "total_gib": 100,
                "used_gib": 80,
                "free_gib": 20,
                "used_percent": 80,
                "free_percent": 20,
            },
            "guard": {
                "threshold_gib": 20,
                "target_gib": 30,
                "interval_seconds": 60,
                "loaded": True,
                "enabled": True,
                "state": "not running",
                "runs": 5,
                "last_exit_code": 0,
                "pressure_active": True,
                "last_check": "2026-09-26T11:59:00+08:00",
                "last_event": {
                    "status": "pressure_remains",
                    "reclaimed_gib": 1.5,
                },
            },
            "resources": {
                "system": {},
                "processes": {"cpu": [], "memory": []},
                "guard": {
                    "loaded": True,
                    "enabled": True,
                    "runs": 5,
                    "last_exit_code": 0,
                },
            },
            "builds": {"count": 0, "items": []},
        }
        with mock.patch.object(
            server, "current_status", return_value=complete
        ):
            projected = server.extension_status()

        cleanup_state = projected["automatic_cleanup"]
        self.assertTrue(cleanup_state["enabled"])
        self.assertTrue(cleanup_state["healthy"])
        self.assertTrue(cleanup_state["pressure_active"])
        self.assertFalse(cleanup_state["running"])
        serialized = json.dumps(projected)
        self.assertNotIn("token", serialized)
        self.assertNotIn("/private/", serialized)
        self.assertNotIn("command", serialized)


class HttpBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.httpd = ThreadingHTTPServer(
            ("127.0.0.1", 0), server.DashboardHandler
        )
        self.original_port = server.PORT
        server.PORT = self.httpd.server_address[1]
        self.thread = threading.Thread(
            target=self.httpd.serve_forever, daemon=True
        )
        self.thread.start()
        self.status_patch = mock.patch.object(
            server, "current_status", return_value={"full": "private"}
        )
        self.extension_patch = mock.patch.object(
            server, "extension_status", return_value={"safe": True}
        )
        self.status_patch.start()
        self.extension_patch.start()

    def tearDown(self) -> None:
        self.status_patch.stop()
        self.extension_patch.stop()
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=3)
        server.PORT = self.original_port

    def request(
        self,
        method: str,
        path: str,
        *,
        origin: str | None = None,
        host: str | None = None,
        body: str | None = None,
    ) -> http.client.HTTPResponse:
        connection = http.client.HTTPConnection(
            "127.0.0.1", self.httpd.server_address[1], timeout=3
        )
        headers = {
            "Host": host
            or f"127.0.0.1:{self.httpd.server_address[1]}"
        }
        if origin is not None:
            headers["Origin"] = origin
        if body is not None:
            headers["Content-Type"] = "application/json"
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        response.body = response.read()
        connection.close()
        return response

    def test_extension_origin_can_read_only_projection(self) -> None:
        projected = self.request(
            "GET",
            "/api/extension/status",
            origin=EXTENSION_ORIGIN,
        )
        full = self.request(
            "GET", "/api/status", origin=EXTENSION_ORIGIN
        )

        self.assertEqual(projected.status, 200)
        self.assertEqual(
            projected.getheader("Access-Control-Allow-Origin"),
            EXTENSION_ORIGIN,
        )
        self.assertEqual(full.status, 403)
        self.assertIsNone(
            full.getheader("Access-Control-Allow-Origin")
        )

    def test_unknown_origin_cannot_read_extension_projection(self) -> None:
        response = self.request(
            "GET",
            "/api/extension/status",
            origin="https://attacker.example",
        )
        self.assertEqual(response.status, 403)

    def test_store_extension_origin_can_read_projection(self) -> None:
        response = self.request(
            "GET",
            "/api/extension/status",
            origin=STORE_EXTENSION_ORIGIN,
        )
        self.assertEqual(response.status, 200)
        self.assertEqual(
            response.getheader("Access-Control-Allow-Origin"),
            STORE_EXTENSION_ORIGIN,
        )

    def test_extension_origin_cannot_post_cleanup(self) -> None:
        response = self.request(
            "POST",
            "/api/cleanup/scan",
            origin=EXTENSION_ORIGIN,
            body="{}",
        )
        self.assertEqual(response.status, 403)

    def test_post_without_browser_origin_is_rejected(self) -> None:
        response = self.request(
            "POST",
            "/api/cleanup/scan",
            body="{}",
        )
        self.assertEqual(response.status, 403)

    def test_unexpected_host_is_rejected(self) -> None:
        response = self.request(
            "GET",
            "/api/extension/status",
            host="attacker.example",
        )
        self.assertEqual(response.status, 403)


if __name__ == "__main__":
    unittest.main()
