from __future__ import annotations

import importlib.util
import signal
import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
RESOURCE_PATH = ROOT / "companion/resource_guard.py"
SPEC = importlib.util.spec_from_file_location(
    "resource_guard_under_test", RESOURCE_PATH
)
assert SPEC is not None and SPEC.loader is not None
resource_guard = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = resource_guard
SPEC.loader.exec_module(resource_guard)


class ResourceGuardTests(unittest.TestCase):
    def test_invalid_threshold_configuration_fails_closed(self) -> None:
        with mock.patch.object(
            resource_guard, "CPU_THRESHOLD_PERCENT", -1
        ):
            with self.assertRaisesRegex(
                SystemExit, "positive finite value"
            ):
                resource_guard.validate_configuration()

    def test_recovered_candidate_clears_previous_signal(self) -> None:
        identity = "12345:1.000:/private/tmp/example.test"
        row = {
            "pid": 12345,
            "ppid": 1,
            "uid": resource_guard.os.getuid(),
            "command": "/private/tmp/example.test",
            "cpu_percent": 0.0,
            "rss_bytes": 0,
            "elapsed_seconds": 3600,
        }
        previous = {
            "candidates": {
                identity: {
                    "cpu_streak": 0,
                    "memory_streak": 0,
                    "signal": "SIGTERM",
                    "signal_time": 1.0,
                }
            }
        }
        with (
            mock.patch.object(
                resource_guard, "load_json", return_value=previous
            ),
            mock.patch.object(
                resource_guard, "process_rows", return_value=[row]
            ),
            mock.patch.object(
                resource_guard,
                "candidate_test_path",
                return_value=Path("/private/tmp/example.test"),
            ),
            mock.patch.object(
                resource_guard,
                "process_identity",
                return_value=identity,
            ),
            mock.patch.object(
                resource_guard,
                "memory_snapshot",
                return_value={
                    "available_percent": 50,
                    "swap_used_gib": 0,
                },
            ),
            mock.patch.object(
                resource_guard.os,
                "getloadavg",
                return_value=(0.0, 0.0, 0.0),
            ),
            mock.patch.object(
                resource_guard.psutil,
                "cpu_percent",
                return_value=0.0,
            ),
            mock.patch.object(
                resource_guard.psutil,
                "cpu_count",
                return_value=8,
            ),
        ):
            state = resource_guard.evaluate()

        candidate = state["candidates"][identity]
        self.assertIsNone(candidate["signal"])
        self.assertIsNone(candidate["signal_time"])

    def test_first_signal_accepts_missing_previous_timestamp(self) -> None:
        row = {
            "pid": 12345,
            "command": "/private/tmp/example.test",
            "cpu_percent": 250.0,
            "rss_bytes": 5 * resource_guard.GIB,
            "elapsed_seconds": 3600,
        }
        previous = {"signal": None, "signal_time": None}
        with (
            mock.patch.object(
                resource_guard,
                "process_still_matches",
                return_value=(True, "matched"),
            ),
            mock.patch.object(resource_guard.os, "kill") as kill,
        ):
            action = resource_guard.terminate_process(
                row,
                "12345:1.000:/private/tmp/example.test",
                previous,
                ["sustained_cpu"],
            )

        self.assertEqual(action["result"], "signaled")
        self.assertEqual(action["signal"], "SIGTERM")
        kill.assert_called_once_with(12345, signal.SIGTERM)


if __name__ == "__main__":
    unittest.main()
