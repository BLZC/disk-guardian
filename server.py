#!/usr/bin/env python3
"""Local-only live dashboard for Disk Guardian."""

from __future__ import annotations

import json
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

from cleanup import CleanupManager
from system_metrics import STORE, current_status


HOST = "127.0.0.1"
PORT = int(os.environ.get("DISK_GUARDIAN_PORT", "18765"))
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "dist"
EXTENSION_ORIGINS = {
    origin.strip()
    for origin in os.environ.get(
        "DISK_GUARDIAN_EXTENSION_ORIGINS",
        "chrome-extension://ccpomkognonnccbjmiapheoadpnepnde,"
        "chrome-extension://knfhjpciofoakljbmneaaailglnmamlk",
    ).split(",")
    if origin.strip().startswith("chrome-extension://")
}

MIME_TYPES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
}


CLEANUP = CleanupManager()


def extension_status() -> dict[str, Any]:
    status = current_status()
    resources = status["resources"]
    resource_guard = resources["guard"]
    disk_guard = status["guard"]
    last_event = disk_guard.get("last_event")
    if not isinstance(last_event, dict):
        last_event = {}
    automatic_cleanup_enabled = bool(
        disk_guard.get("loaded") and disk_guard.get("enabled")
    )
    automatic_cleanup_running = (
        disk_guard.get("state") == "running"
    )
    pressure_active = bool(disk_guard.get("pressure_active"))
    return {
        "product": "disk-guardian",
        "api_version": 2,
        "timestamp": status["timestamp"],
        "disk": status["disk"],
        "guard": {
            key: disk_guard.get(key)
            for key in (
                "threshold_gib",
                "target_gib",
                "interval_seconds",
                "loaded",
                "enabled",
                "runs",
                "last_exit_code",
                "pressure_active",
            )
        },
        "automatic_cleanup": {
            "enabled": automatic_cleanup_enabled,
            "healthy": (
                automatic_cleanup_enabled
                and disk_guard.get("last_exit_code") in {None, 0}
            ),
            "running": automatic_cleanup_running,
            "pressure_active": pressure_active,
            "trigger_free_gib": disk_guard.get("threshold_gib"),
            "target_free_gib": disk_guard.get("target_gib"),
            "interval_seconds": disk_guard.get("interval_seconds"),
            "last_check": disk_guard.get("last_check"),
            "last_result": last_event.get("status"),
            "last_reclaimed_gib": last_event.get("reclaimed_gib"),
            "scope": "verified_rebuildable_artifacts_only",
        },
        "resources": {
            "system": resources["system"],
            "processes": resources["processes"],
            "guard": {
                key: resource_guard.get(key)
                for key in (
                    "loaded",
                    "enabled",
                    "runs",
                    "last_exit_code",
                    "status",
                    "last_check",
                    "system_pressure",
                    "candidate_count",
                )
            },
        },
        "build_count": status["builds"]["count"],
    }


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "DiskGuardian/0.2"

    def do_GET(self) -> None:
        if not self._request_host_is_local():
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        route = urlparse(self.path).path
        if route.startswith("/api/") and self._request_has_foreign_origin(
            allow_extension=route == "/api/extension/status"
        ):
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        if route == "/api/status":
            self._send_json(current_status())
            return
        if route == "/api/extension/status":
            self._send_json(
                extension_status(),
                allow_extension_origin=True,
            )
            return
        if route == "/api/cleanup/latest":
            self._send_json({"receipt": CLEANUP.latest()})
            return
        static = MIME_TYPES.get(route)
        if static is None:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        filename, content_type = static
        try:
            payload = (STATIC_DIR / filename).read_bytes()
        except OSError:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; style-src 'self'; script-src 'self'; "
            "connect-src 'self'; img-src 'self' data:; object-src 'none'; "
            "base-uri 'none'; frame-ancestors 'none'",
        )
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self._write_payload(payload)

    def do_POST(self) -> None:
        route = urlparse(self.path).path
        if (
            not self._request_host_is_local()
            or
            not self._request_is_local()
            or not self._request_is_same_origin()
        ):
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        if route == "/api/cleanup/scan":
            self._send_json({"plan": CLEANUP.scan()})
            return
        if route == "/api/cleanup/execute":
            body = self._read_json_body()
            if body is None:
                return
            token = body.get("token")
            candidate_ids = body.get("candidate_ids")
            if (
                not isinstance(token, str)
                or not isinstance(candidate_ids, list)
                or not all(
                    isinstance(candidate_id, str)
                    for candidate_id in candidate_ids
                )
            ):
                self._send_json(
                    {"error": "invalid_request"},
                    status=HTTPStatus.BAD_REQUEST,
                )
                return
            try:
                receipt = CLEANUP.execute(token, candidate_ids)
            except ValueError as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return
            self._send_json({"receipt": receipt})
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def _request_is_local(self) -> bool:
        return self.client_address[0] in {"127.0.0.1", "::1"}

    def _request_host_is_local(self) -> bool:
        return self.headers.get("Host") == f"{HOST}:{PORT}"

    def _request_has_foreign_origin(
        self, *, allow_extension: bool = False
    ) -> bool:
        allowed = f"http://{HOST}:{PORT}"
        origin = self.headers.get("Origin")
        if origin:
            return not (
                origin == allowed
                or (allow_extension and origin in EXTENSION_ORIGINS)
            )
        referer = self.headers.get("Referer")
        if not referer:
            return False
        parsed = urlparse(referer)
        return not (
            parsed.scheme == "http"
            and parsed.hostname == HOST
            and parsed.port == PORT
        )

    def _request_is_same_origin(self) -> bool:
        allowed = f"http://{HOST}:{PORT}"
        origin = self.headers.get("Origin")
        if origin:
            return origin == allowed
        referer = self.headers.get("Referer")
        if referer:
            parsed = urlparse(referer)
            return (
                parsed.scheme == "http"
                and parsed.hostname == HOST
                and parsed.port == PORT
            )
        return False

    def _read_json_body(self) -> Optional[dict[str, Any]]:
        try:
            content_length = int(
                self.headers.get("Content-Length", "0")
            )
        except ValueError:
            self._send_json(
                {"error": "invalid_content_length"},
                status=HTTPStatus.BAD_REQUEST,
            )
            return None
        if content_length <= 0 or content_length > 64 * 1024:
            self._send_json(
                {"error": "invalid_body_size"},
                status=HTTPStatus.BAD_REQUEST,
            )
            return None
        try:
            value = json.loads(self.rfile.read(content_length))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._send_json(
                {"error": "invalid_json"},
                status=HTTPStatus.BAD_REQUEST,
            )
            return None
        if not isinstance(value, dict):
            self._send_json(
                {"error": "invalid_request"},
                status=HTTPStatus.BAD_REQUEST,
            )
            return None
        return value

    def _send_json(
        self,
        value: Any,
        status: HTTPStatus = HTTPStatus.OK,
        *,
        allow_extension_origin: bool = False,
    ) -> None:
        payload = json.dumps(
            value, ensure_ascii=False, separators=(",", ":")
        ).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        origin = self.headers.get("Origin")
        if allow_extension_origin and origin in EXTENSION_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.end_headers()
        self._write_payload(payload)

    def _write_payload(self, payload: bytes) -> None:
        try:
            self.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, format: str, *args: Any) -> None:
        if os.environ.get("DISK_GUARDIAN_ACCESS_LOG") == "1":
            super().log_message(format, *args)


def main() -> int:
    STATIC_DIR.resolve(strict=True)
    STORE.start()
    server = ThreadingHTTPServer((HOST, PORT), DashboardHandler)
    print(
        f"Disk Guardian listening at http://{HOST}:{PORT}",
        flush=True,
    )
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        STORE.stop()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
