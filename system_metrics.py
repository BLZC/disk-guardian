#!/usr/bin/env python3
"""Read-only system metrics and launchd state for Disk Guardian."""

from __future__ import annotations

import json
import os
import plistlib
import shutil
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

import psutil

from cleanup_policy import (
    BUILD_RE,
    DATA_VOLUME,
    GIB,
    GOCACHE,
    GO_TEMP_RE,
    ISOLATED_CACHE_RE,
    MIB,
    PRIVATE_TMP,
    TEST_RE,
    darwin_temp_dir,
    du_bytes,
    run_text,
)


HOME = Path.home().resolve()
STATE_DIR = Path(
    os.environ.get(
        "DISK_GUARDIAN_STATE_DIR",
        str(HOME / "Library/Application Support/Disk Guardian"),
    )
).resolve()
GUARD_STATE = STATE_DIR / "disk_guard_state.json"
GUARD_LABEL_NAME = os.environ.get(
    "DISK_GUARDIAN_DISK_LABEL",
    "io.github.blzc.disk-guardian.disk-guard",
)
GUARD_PLIST = HOME / f"Library/LaunchAgents/{GUARD_LABEL_NAME}.plist"
GUARD_LABEL = f"gui/{os.getuid()}/{GUARD_LABEL_NAME}"
RESOURCE_STATE = STATE_DIR / "resource_guard_state.json"
RESOURCE_LABEL_NAME = os.environ.get(
    "DISK_GUARDIAN_RESOURCE_LABEL",
    "io.github.blzc.disk-guardian.resource-guard",
)
RESOURCE_PLIST = (
    HOME / f"Library/LaunchAgents/{RESOURCE_LABEL_NAME}.plist"
)
RESOURCE_LABEL = f"gui/{os.getuid()}/{RESOURCE_LABEL_NAME}"


def round_gib(value: int) -> float:
    return round(value / GIB, 2)


def iso_now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def read_guard_config() -> dict[str, int]:
    defaults = {
        "threshold_gib": 10,
        "target_gib": 20,
        "min_age_seconds": 3600,
        "cache_quiet_seconds": 300,
        "interval_seconds": 60,
    }
    try:
        with GUARD_PLIST.open("rb") as handle:
            plist = plistlib.load(handle)
        environment = plist.get("EnvironmentVariables", {})
        defaults.update(
            {
                "threshold_gib": int(
                    environment.get("DISK_GUARDIAN_THRESHOLD_GIB", 10)
                ),
                "target_gib": int(
                    environment.get("DISK_GUARDIAN_TARGET_GIB", 20)
                ),
                "min_age_seconds": int(
                    max(
                        3600,
                        int(
                            environment.get(
                                "DISK_GUARDIAN_MIN_AGE_SECONDS",
                                3600,
                            )
                        ),
                    )
                ),
                "cache_quiet_seconds": int(
                    max(
                        300,
                        int(
                            environment.get(
                                "DISK_GUARDIAN_CACHE_QUIET_SECONDS",
                                300,
                            )
                        ),
                    )
                ),
                "interval_seconds": int(plist.get("StartInterval", 60)),
            }
        )
    except (OSError, ValueError, TypeError, plistlib.InvalidFileException):
        pass
    return defaults


def launch_runtime(label: str) -> dict[str, Any]:
    result: dict[str, Any] = {
        "loaded": False,
        "enabled": False,
        "state": "unknown",
        "runs": 0,
        "last_exit_code": None,
    }
    rc, output, _ = run_text(
        ["/bin/launchctl", "print", label], timeout=4
    )
    if rc == 0:
        result["loaded"] = True
        for line in output.splitlines():
            stripped = line.strip()
            if stripped.startswith("state ="):
                result["state"] = stripped.split("=", 1)[1].strip()
            elif stripped.startswith("runs ="):
                try:
                    result["runs"] = int(
                        stripped.split("=", 1)[1].strip()
                    )
                except ValueError:
                    pass
            elif stripped.startswith("last exit code ="):
                try:
                    result["last_exit_code"] = int(
                        stripped.split("=", 1)[1].strip()
                    )
                except ValueError:
                    pass
    rc, output, _ = run_text(
        ["/bin/launchctl", "print-disabled", f"gui/{os.getuid()}"],
        timeout=4,
    )
    result["enabled"] = (
        rc == 0
        and f'"{label.rsplit("/", 1)[-1]}" => enabled' in output
    )
    return result


def resource_guard_config() -> dict[str, Any]:
    defaults: dict[str, Any] = {
        "interval_seconds": 60,
        "cpu_threshold_percent": 200.0,
        "memory_threshold_gib": 4.0,
        "cpu_streak_required": 5,
        "memory_streak_required": 3,
        "min_runtime_seconds": 1800,
        "max_runtime_seconds": 7200,
        "scope": "temporary_macho_test_processes_only",
    }
    try:
        with RESOURCE_PLIST.open("rb") as handle:
            plist = plistlib.load(handle)
        environment = plist.get("EnvironmentVariables", {})
        defaults.update(
            {
                "interval_seconds": int(plist.get("StartInterval", 60)),
                "cpu_threshold_percent": float(
                    environment.get(
                        "DISK_GUARDIAN_CPU_THRESHOLD_PERCENT", 200
                    )
                ),
                "memory_threshold_gib": float(
                    environment.get(
                        "DISK_GUARDIAN_MEMORY_THRESHOLD_GIB", 4
                    )
                ),
                "cpu_streak_required": int(
                    environment.get(
                        "DISK_GUARDIAN_CPU_STREAK_REQUIRED", 5
                    )
                ),
                "memory_streak_required": int(
                    environment.get(
                        "DISK_GUARDIAN_MEMORY_STREAK_REQUIRED", 3
                    )
                ),
                "min_runtime_seconds": int(
                    environment.get(
                        "DISK_GUARDIAN_MIN_RUNTIME_SECONDS", 1800
                    )
                ),
                "max_runtime_seconds": int(
                    environment.get(
                        "DISK_GUARDIAN_MAX_RUNTIME_SECONDS", 7200
                    )
                ),
            }
        )
    except (OSError, ValueError, TypeError, plistlib.InvalidFileException):
        pass
    return defaults


def active_builds() -> list[dict[str, Any]]:
    rc, output, _ = run_text(
        ["/bin/ps", "-axo", "pid=,etime=,command="], timeout=4
    )
    if rc != 0:
        return []
    items: list[dict[str, Any]] = []
    for line in output.splitlines():
        parts = line.strip().split(maxsplit=2)
        if len(parts) != 3 or not parts[0].isdigit():
            continue
        pid, elapsed, command = parts
        if BUILD_RE.search(command):
            items.append(
                {
                    "pid": int(pid),
                    "elapsed": elapsed,
                    "command": command[:280],
                }
            )
    return items[:20]


def elapsed_seconds(value: str) -> int:
    try:
        days = 0
        rest = value
        if "-" in rest:
            day_text, rest = rest.split("-", 1)
            days = int(day_text)
        parts = [int(part) for part in rest.split(":")]
        if len(parts) == 3:
            hours, minutes, seconds = parts
        elif len(parts) == 2:
            hours = 0
            minutes, seconds = parts
        else:
            return 0
        return days * 86400 + hours * 3600 + minutes * 60 + seconds
    except (TypeError, ValueError):
        return 0


def process_rankings() -> dict[str, list[dict[str, Any]]]:
    rc, output, _ = run_text(
        [
            "/bin/ps",
            "-axo",
            "pid=,ppid=,uid=,%cpu=,rss=,etime=,comm=",
        ],
        timeout=5,
    )
    if rc != 0:
        return {"cpu": [], "memory": []}
    raw_items: list[dict[str, Any]] = []
    for line in output.splitlines():
        parts = line.strip().split(maxsplit=6)
        if len(parts) != 7:
            continue
        pid, ppid, uid, cpu, rss, elapsed, name = parts
        try:
            raw_items.append(
                {
                    "pid": int(pid),
                    "ppid": int(ppid),
                    "uid": int(uid),
                    "cpu_percent": round(float(cpu), 1),
                    "rss_gib": round(int(rss) * 1024 / GIB, 2),
                    "elapsed_seconds": elapsed_seconds(elapsed),
                    "elapsed": elapsed,
                    "name": Path(name).name[:80] or name[:80],
                    "owned": int(uid) == os.getuid(),
                }
            )
        except ValueError:
            continue
    by_pid = {item["pid"]: item for item in raw_items}

    def is_dashboard_process(item: dict[str, Any]) -> bool:
        current = item
        seen: set[int] = set()
        while current and current["pid"] not in seen:
            seen.add(current["pid"])
            name = str(current.get("name", ""))
            if current["pid"] == os.getpid() or "disk-guardian" in name:
                return True
            current = by_pid.get(current.get("ppid"))
        return False

    items = [
        item for item in raw_items if not is_dashboard_process(item)
    ]
    return {
        "cpu": sorted(
            items,
            key=lambda item: item["cpu_percent"],
            reverse=True,
        )[:8],
        "memory": sorted(
            items,
            key=lambda item: item["rss_gib"],
            reverse=True,
        )[:8],
    }


def resource_status() -> dict[str, Any]:
    virtual = psutil.virtual_memory()
    swap = psutil.swap_memory()
    load_1, load_5, load_15 = os.getloadavg()
    state = read_json(RESOURCE_STATE)
    runtime = launch_runtime(RESOURCE_LABEL)
    config = resource_guard_config()
    return {
        "system": {
            "cpu_percent": round(psutil.cpu_percent(interval=0.08), 1),
            "logical_cpus": psutil.cpu_count(logical=True),
            "load_average": [
                round(load_1, 2),
                round(load_5, 2),
                round(load_15, 2),
            ],
            "memory_total_gib": round_gib(virtual.total),
            "memory_used_gib": round_gib(virtual.used),
            "memory_available_gib": round_gib(virtual.available),
            "memory_used_percent": round(
                virtual.used / virtual.total * 100, 1
            ),
            "memory_available_percent": round(
                virtual.available / virtual.total * 100, 1
            ),
            "swap_used_gib": round_gib(swap.used),
            "swap_total_gib": round_gib(swap.total),
            "swap_percent": (
                round(swap.used / swap.total * 100, 1)
                if swap.total
                else 0
            ),
        },
        "processes": process_rankings(),
        "guard": {
            **config,
            **runtime,
            "status": state.get("status"),
            "last_check": state.get("time"),
            "system_pressure": state.get("system_pressure", False),
            "candidate_count": state.get("candidate_count", 0),
            "alerts": state.get("alerts", []),
            "last_action": state.get("last_action"),
            "action_history": state.get("action_history", []),
        },
    }


def sum_candidates(root: Path, predicate: Any) -> tuple[int, int]:
    count = 0
    total = 0
    try:
        children = list(root.iterdir())
    except OSError:
        return count, total
    for child in children:
        try:
            if not predicate(child):
                continue
        except OSError:
            continue
        size = du_bytes(child)
        count += 1
        if size is not None:
            total += size
    return count, total


class MetricsStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._details: dict[str, Any] = {
            "sampled_at": None,
            "go_cache_gib": None,
            "module_cache_gib": None,
            "module_cache_sampled_at": None,
            "go_temp_count": 0,
            "go_temp_gib": 0,
            "test_binary_count": 0,
            "test_binary_gib": 0,
            "isolated_cache_count": 0,
            "isolated_cache_gib": 0,
        }
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._sample_loop,
            name="disk-dashboard-sampler",
            daemon=True,
        )

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _sample_loop(self) -> None:
        while not self._stop.is_set():
            self._sample_details()
            self._stop.wait(60)

    def _sample_details(self) -> None:
        go_cache = du_bytes(GOCACHE, timeout=45)
        temp_root = darwin_temp_dir()
        go_temp_count = 0
        go_temp_bytes = 0
        if temp_root is not None:
            go_temp_count, go_temp_bytes = sum_candidates(
                temp_root,
                lambda path: path.is_dir()
                and GO_TEMP_RE.fullmatch(path.name) is not None,
            )
        test_count, test_bytes = sum_candidates(
            PRIVATE_TMP,
            lambda path: path.is_file()
            and TEST_RE.fullmatch(path.name) is not None
            and path.stat().st_size >= 100 * MIB,
        )
        isolated_count, isolated_bytes = sum_candidates(
            PRIVATE_TMP,
            lambda path: path.is_dir()
            and ISOLATED_CACHE_RE.fullmatch(path.name) is not None,
        )
        details = {
            "sampled_at": iso_now(),
            "go_cache_gib": (
                round_gib(go_cache) if go_cache is not None else None
            ),
            "module_cache_gib": None,
            "module_cache_sampled_at": None,
            "go_temp_count": go_temp_count,
            "go_temp_gib": round_gib(go_temp_bytes),
            "test_binary_count": test_count,
            "test_binary_gib": round_gib(test_bytes),
            "isolated_cache_count": isolated_count,
            "isolated_cache_gib": round_gib(isolated_bytes),
        }
        with self._lock:
            self._details = details

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._details)


STORE = MetricsStore()


def current_status() -> dict[str, Any]:
    usage = shutil.disk_usage(DATA_VOLUME)
    config = read_guard_config()
    state = read_json(GUARD_STATE)
    runtime = launch_runtime(GUARD_LABEL)
    builds = active_builds()
    pressure = bool(state.get("pressure_active", False)) or (
        usage.free < config["threshold_gib"] * GIB
    )
    if usage.free >= config["target_gib"] * GIB:
        pressure = False
    return {
        "timestamp": iso_now(),
        "disk": {
            "total_gib": round_gib(usage.total),
            "used_gib": round_gib(usage.used),
            "free_gib": round_gib(usage.free),
            "used_percent": round(usage.used / usage.total * 100, 1),
            "free_percent": round(usage.free / usage.total * 100, 1),
        },
        "guard": {
            **config,
            **runtime,
            "pressure_active": pressure,
            "last_check": state.get("last_check"),
            "last_event": state.get("last_event"),
        },
        "builds": {"count": len(builds), "items": builds},
        "storage": STORE.snapshot(),
        "resources": resource_status(),
    }
