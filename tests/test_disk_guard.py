from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GUARD_PATH = ROOT / "companion/disk_guard.py"
SPEC = importlib.util.spec_from_file_location(
    "disk_guard_under_test", GUARD_PATH
)
assert SPEC is not None and SPEC.loader is not None
disk_guard = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = disk_guard
SPEC.loader.exec_module(disk_guard)


class DiskGuardTests(unittest.TestCase):
    def test_pressure_state_uses_hysteresis(self) -> None:
        threshold = disk_guard.THRESHOLD_GIB * disk_guard.GIB
        target = disk_guard.TARGET_GIB * disk_guard.GIB

        self.assertTrue(
            disk_guard.pressure_state(threshold - 1, {})
        )
        self.assertTrue(
            disk_guard.pressure_state(
                threshold + 1, {"pressure_active": True}
            )
        )
        self.assertFalse(
            disk_guard.pressure_state(target, {"pressure_active": True})
        )


if __name__ == "__main__":
    unittest.main()
