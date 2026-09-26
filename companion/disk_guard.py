#!/usr/bin/env python3
"""Threshold controller for Disk Guardian's canonical cleanup policy."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


INSTALL_DIR = Path(__file__).resolve().parent.parent
if str(INSTALL_DIR) not in sys.path:
    sys.path.insert(0, str(INSTALL_DIR))

# The executable lives in companion/, while shared modules live one level up.
from cleanup import CleanupManager  # noqa: E402
from cleanup_policy import GIB, free_bytes, gib, process_snapshot  # noqa: E402


STATE_DIR = Path(
    os.environ.get(
        "DISK_GUARDIAN_STATE_DIR",
        str(
            Path.home().resolve()
            / "Library/Application Support/Disk Guardian"
        ),
    )
).resolve()
STATE_PATH = STATE_DIR / "disk_guard_state.json"

THRESHOLD_GIB = int(
    os.environ.get("DISK_GUARDIAN_THRESHOLD_GIB", "20")
)
TARGET_GIB = int(
    os.environ.get("DISK_GUARDIAN_TARGET_GIB", "30")
)
HEALTHY_HEARTBEAT_SECONDS = int(
    os.environ.get(
        "DISK_GUARDIAN_HEALTHY_HEARTBEAT_SECONDS", "3600"
    )
)
DRY_RUN = "--dry-run" in sys.argv
STATUS_ONLY = "--status" in sys.argv
VERBOSE = "--verbose" in sys.argv or STATUS_ONLY or DRY_RUN


def now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .astimezone()
        .isoformat(timespec="seconds")
    )


def parse_timestamp(value: Any) -> float:
    if not isinstance(value, str):
        return 0
    try:
        return datetime.fromisoformat(value).timestamp()
    except ValueError:
        return 0


def load_state() -> dict[str, Any]:
    try:
        value = json.loads(STATE_PATH.read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(value: dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=".disk_guard_state.", dir=str(STATE_DIR)
    )
    try:
        with os.fdopen(descriptor, "w") as handle:
            json.dump(
                value,
                handle,
                ensure_ascii=False,
                sort_keys=True,
            )
            handle.write("\n")
        os.replace(temporary, STATE_PATH)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def emit(value: dict[str, Any]) -> None:
    print(
        json.dumps(value, ensure_ascii=False, sort_keys=True),
        flush=True,
    )


def pressure_state(
    current_free_bytes: int, previous: dict[str, Any]
) -> bool:
    active = bool(previous.get("pressure_active", False))
    if current_free_bytes < THRESHOLD_GIB * GIB:
        return True
    if current_free_bytes >= TARGET_GIB * GIB:
        return False
    return active


def main() -> int:
    if THRESHOLD_GIB <= 0 or TARGET_GIB <= THRESHOLD_GIB:
        raise SystemExit(
            "target must be greater than a positive threshold"
        )

    before = free_bytes()
    state = load_state()
    pressure_active = pressure_state(before, state)

    if STATUS_ONLY:
        emit(
            {
                "time": now_iso(),
                "status": (
                    "pressure" if pressure_active else "healthy"
                ),
                "free_gib": gib(before),
                "threshold_gib": THRESHOLD_GIB,
                "target_gib": TARGET_GIB,
                "active_builds": (process_snapshot() or [])[:5],
            }
        )
        return 0

    if not pressure_active:
        event = {
            "time": now_iso(),
            "status": "healthy",
            "free_gib": gib(before),
            "threshold_gib": THRESHOLD_GIB,
            "target_gib": TARGET_GIB,
        }
        if VERBOSE:
            emit(event)
        heartbeat_due = (
            bool(state.get("pressure_active", False))
            or time.time()
            - parse_timestamp(state.get("last_check"))
            >= HEALTHY_HEARTBEAT_SECONDS
        )
        if heartbeat_due and not DRY_RUN:
            save_state(
                {
                    "pressure_active": False,
                    "last_check": event["time"],
                    "last_free_bytes": before,
                    "last_event": event,
                }
            )
        return 0

    try:
        outcome = CleanupManager().automatic_cleanup(
            TARGET_GIB * GIB,
            dry_run=DRY_RUN,
        )
    except ValueError as error:
        if str(error) != "cleanup_busy":
            raise
        event = {
            "time": now_iso(),
            "status": "cleanup_busy",
            "before_free_gib": gib(before),
            "after_free_gib": gib(free_bytes()),
            "reclaimed_gib": 0,
            "threshold_gib": THRESHOLD_GIB,
            "target_gib": TARGET_GIB,
            "actions": [],
        }
        emit(event)
        return 0

    after = free_bytes()
    remains = after < TARGET_GIB * GIB
    event = {
        "time": now_iso(),
        "status": (
            "dry_run"
            if DRY_RUN
            else ("pressure_remains" if remains else "recovered")
        ),
        "threshold_gib": THRESHOLD_GIB,
        "target_gib": TARGET_GIB,
        **outcome,
    }
    emit(event)
    if not DRY_RUN:
        save_state(
            {
                "pressure_active": remains,
                "last_check": event["time"],
                "last_free_bytes": after,
                "last_event": event,
            }
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
