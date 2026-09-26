#!/usr/bin/env python3
"""Conservative CPU/memory guard for temporary test processes on this Mac."""

from __future__ import annotations

import fcntl
import json
import math
import os
import re
import signal
# Security: calls use fixed absolute system binaries with shell disabled.
import subprocess  # nosec B404
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import psutil


GIB = 1024**3
HOME = Path.home().resolve()
STATE_DIR = Path(
    os.environ.get(
        "DISK_GUARDIAN_STATE_DIR",
        str(HOME / "Library/Application Support/Disk Guardian"),
    )
).resolve()
STATE_PATH = STATE_DIR / "resource_guard_state.json"
LOCK_PATH = STATE_DIR / "resource_guard.lock"

CPU_THRESHOLD_PERCENT = float(
    os.environ.get("DISK_GUARDIAN_CPU_THRESHOLD_PERCENT", "200")
)
MEMORY_THRESHOLD_GIB = float(
    os.environ.get("DISK_GUARDIAN_MEMORY_THRESHOLD_GIB", "4")
)
CPU_STREAK_REQUIRED = int(
    os.environ.get("DISK_GUARDIAN_CPU_STREAK_REQUIRED", "5")
)
MEMORY_STREAK_REQUIRED = int(
    os.environ.get("DISK_GUARDIAN_MEMORY_STREAK_REQUIRED", "3")
)
MIN_RUNTIME_SECONDS = int(
    os.environ.get("DISK_GUARDIAN_MIN_RUNTIME_SECONDS", "1800")
)
MAX_RUNTIME_SECONDS = int(
    os.environ.get("DISK_GUARDIAN_MAX_RUNTIME_SECONDS", "7200")
)
ORPHAN_RUNTIME_SECONDS = int(
    os.environ.get("DISK_GUARDIAN_ORPHAN_RUNTIME_SECONDS", "1800")
)
MEMORY_PRESSURE_AVAILABLE_PERCENT = float(
    os.environ.get("DISK_GUARDIAN_MEMORY_AVAILABLE_PERCENT", "12")
)
SWAP_PRESSURE_GIB = float(
    os.environ.get("DISK_GUARDIAN_SWAP_PRESSURE_GIB", "5")
)
TERM_GRACE_SECONDS = int(
    os.environ.get("DISK_GUARDIAN_TERM_GRACE_SECONDS", "120")
)
DRY_RUN = "--dry-run" in os.sys.argv
STATUS_ONLY = "--status" in os.sys.argv
VERBOSE = "--verbose" in os.sys.argv or DRY_RUN or STATUS_ONLY

MACHO_MAGICS = {
    bytes.fromhex("cffaedfe"),
    bytes.fromhex("feedfacf"),
    bytes.fromhex("cafebabe"),
    bytes.fromhex("bebafeca"),
}
TEMP_TEST_RE = re.compile(
    r"^/(?:private/)?(?:tmp|var/folders/[^/]+/[^/]+/T)/.*\.test$"
)


def validate_configuration() -> None:
    numeric_thresholds = {
        "CPU threshold": CPU_THRESHOLD_PERCENT,
        "memory threshold": MEMORY_THRESHOLD_GIB,
        "swap pressure threshold": SWAP_PRESSURE_GIB,
    }
    for label, value in numeric_thresholds.items():
        if not math.isfinite(value) or value <= 0:
            raise SystemExit(f"{label} must be a positive finite value")
    if (
        not math.isfinite(MEMORY_PRESSURE_AVAILABLE_PERCENT)
        or not 0 < MEMORY_PRESSURE_AVAILABLE_PERCENT <= 100
    ):
        raise SystemExit(
            "memory available threshold must be within (0, 100]"
        )
    if CPU_STREAK_REQUIRED < 2 or MEMORY_STREAK_REQUIRED < 2:
        raise SystemExit("streak thresholds must be at least 2")
    if MIN_RUNTIME_SECONDS < 300:
        raise SystemExit("minimum runtime must be at least 300 seconds")
    if ORPHAN_RUNTIME_SECONDS < MIN_RUNTIME_SECONDS:
        raise SystemExit(
            "orphan runtime must be at least the minimum runtime"
        )
    if MAX_RUNTIME_SECONDS < MIN_RUNTIME_SECONDS:
        raise SystemExit(
            "maximum runtime must be at least the minimum runtime"
        )
    if TERM_GRACE_SECONDS < 30:
        raise SystemExit("termination grace must be at least 30 seconds")


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(
        timespec="seconds"
    )


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_json(path: Path, value: dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=str(STATE_DIR)
    )
    try:
        with os.fdopen(descriptor, "w") as handle:
            json.dump(value, handle, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
        os.replace(temporary, path)
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


def memory_snapshot() -> dict[str, Any]:
    virtual = psutil.virtual_memory()
    swap = psutil.swap_memory()
    return {
        "total_gib": round(virtual.total / GIB, 2),
        "used_gib": round(virtual.used / GIB, 2),
        "available_gib": round(virtual.available / GIB, 2),
        "available_percent": round(
            virtual.available / virtual.total * 100, 1
        ),
        "swap_used_gib": round(swap.used / GIB, 2),
        "swap_total_gib": round(swap.total / GIB, 2),
    }


def parse_elapsed_seconds(value: str) -> int:
    try:
        days = 0
        rest = value
        if "-" in rest:
            day_text, rest = rest.split("-", 1)
            days = int(day_text)
        pieces = [int(piece) for piece in rest.split(":")]
        if len(pieces) == 3:
            hours, minutes, seconds = pieces
        elif len(pieces) == 2:
            hours = 0
            minutes, seconds = pieces
        else:
            return 0
        return days * 86400 + hours * 3600 + minutes * 60 + seconds
    except (TypeError, ValueError):
        return 0


def process_rows() -> Optional[list[dict[str, Any]]]:
    try:
        result = subprocess.run(  # nosec B603
            [
                "/bin/ps",
                "-axo",
                "pid=,ppid=,uid=,%cpu=,rss=,etime=,command=",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=8,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    rows: list[dict[str, Any]] = []
    for line in result.stdout.splitlines():
        pieces = line.strip().split(maxsplit=6)
        if len(pieces) != 7:
            continue
        pid, ppid, uid, cpu, rss, elapsed, command = pieces
        try:
            rows.append(
                {
                    "pid": int(pid),
                    "ppid": int(ppid),
                    "uid": int(uid),
                    "cpu_percent": float(cpu),
                    "rss_bytes": int(rss) * 1024,
                    "elapsed_seconds": parse_elapsed_seconds(elapsed),
                    "command": command,
                }
            )
        except ValueError:
            continue
    return rows


def allowed_temp_roots() -> list[Path]:
    roots = [Path("/private/tmp").resolve()]
    try:
        result = subprocess.run(  # nosec B603
            ["/usr/bin/getconf", "DARWIN_USER_TEMP_DIR"],
            check=False,
            capture_output=True,
            text=True,
            timeout=3,
        )
        if result.returncode == 0 and result.stdout.strip():
            candidate = Path(result.stdout.strip()).resolve(strict=True)
            if (
                candidate.is_dir()
                and candidate.stat().st_uid == os.getuid()
                and candidate not in roots
            ):
                roots.append(candidate)
    except (OSError, subprocess.TimeoutExpired):
        pass
    return roots


def path_is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def candidate_test_path(command: str) -> Optional[Path]:
    try:
        first = command.split(maxsplit=1)[0]
    except IndexError:
        return None
    if not first.endswith(".test") or not TEMP_TEST_RE.fullmatch(first):
        return None
    path = Path(first)
    try:
        stat = path.lstat()
        real = path.resolve(strict=True)
    except OSError:
        return None
    if (
        not path.is_file()
        or path.is_symlink()
        or stat.st_uid != os.getuid()
        or not any(path_is_within(real, root) for root in allowed_temp_roots())
    ):
        return None
    try:
        with path.open("rb") as handle:
            if handle.read(4) not in MACHO_MAGICS:
                return None
    except OSError:
        return None
    return path


def process_identity(row: dict[str, Any], path: Path) -> str:
    try:
        created = psutil.Process(row["pid"]).create_time()
    except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
        created = 0
    return f"{row['pid']}:{created:.3f}:{path}"


def process_still_matches(
    row: dict[str, Any], identity: str
) -> tuple[bool, str]:
    try:
        expected_pid, expected_created, expected_path = identity.split(
            ":", 2
        )
        process = psutil.Process(row["pid"])
        if process.pid != int(expected_pid):
            return False, "pid_changed"
        if abs(process.create_time() - float(expected_created)) > 0.01:
            return False, "process_replaced"
        uids = process.uids()
        if uids.real != os.getuid():
            return False, "owner_changed"
        command = " ".join(process.cmdline())
        current_path = candidate_test_path(command)
        if current_path is None or str(current_path) != expected_path:
            return False, "command_changed"
        return True, "matched"
    except (
        ValueError,
        psutil.NoSuchProcess,
        psutil.AccessDenied,
        OSError,
    ):
        return False, "process_unavailable"


def terminate_process(
    row: dict[str, Any],
    identity: str,
    previous: dict[str, Any],
    reasons: list[str],
) -> dict[str, Any]:
    previous_signal = previous.get("signal")
    try:
        previous_signal_time = float(
            previous.get("signal_time") or 0
        )
    except (TypeError, ValueError):
        previous_signal_time = 0
    signal_name = "SIGTERM"
    selected_signal = signal.SIGTERM
    action = {
        "time": now_iso(),
        "pid": row["pid"],
        "identity": identity,
        "command": row["command"][:500],
        "cpu_percent": row["cpu_percent"],
        "rss_gib": round(row["rss_bytes"] / GIB, 2),
        "elapsed_seconds": row["elapsed_seconds"],
        "reasons": reasons,
        "signal": signal_name,
        "dry_run": DRY_RUN,
    }
    if STATUS_ONLY:
        action["result"] = "status_only"
        return action
    if previous_signal == "SIGTERM":
        grace_elapsed = time.time() - previous_signal_time
        if grace_elapsed < TERM_GRACE_SECONDS:
            action["result"] = "waiting_grace"
            action["grace_remaining_seconds"] = round(
                TERM_GRACE_SECONDS - grace_elapsed
            )
            return action
        signal_name = "SIGKILL"
        selected_signal = signal.SIGKILL
        action["signal"] = signal_name
    if DRY_RUN:
        action["result"] = "would_signal"
        return action
    matched, match_result = process_still_matches(row, identity)
    if not matched:
        action["result"] = match_result
        return action
    try:
        os.kill(row["pid"], selected_signal)
        action["result"] = "signaled"
    except ProcessLookupError:
        action["result"] = "already_exited"
    except (PermissionError, OSError) as error:
        action["result"] = "error"
        action["error"] = str(error)
    return action


def evaluate() -> dict[str, Any]:
    previous = load_json(STATE_PATH)
    previous_candidates = previous.get("candidates", {})
    if not isinstance(previous_candidates, dict):
        previous_candidates = {}
    rows = process_rows()
    memory = memory_snapshot()
    load_1, load_5, load_15 = os.getloadavg()
    cpu_percent = psutil.cpu_percent(interval=0.2)
    system_pressure = (
        memory["available_percent"]
        < MEMORY_PRESSURE_AVAILABLE_PERCENT
        or memory["swap_used_gib"] >= SWAP_PRESSURE_GIB
    )
    if rows is None:
        return {
            "time": now_iso(),
            "status": "process_check_failed",
            "cpu_percent": cpu_percent,
            "load_average": [load_1, load_5, load_15],
            "memory": memory,
            "candidates": previous_candidates,
            "actions": [],
        }

    next_candidates: dict[str, Any] = {}
    actions: list[dict[str, Any]] = []
    alerts: list[dict[str, Any]] = []
    for row in rows:
        if row["uid"] != os.getuid():
            continue
        path = candidate_test_path(row["command"])
        if path is None:
            continue
        if row["elapsed_seconds"] < MIN_RUNTIME_SECONDS:
            continue
        identity = process_identity(row, path)
        old = previous_candidates.get(identity, {})
        if not isinstance(old, dict):
            old = {}
        cpu_streak = (
            int(old.get("cpu_streak", 0)) + 1
            if row["cpu_percent"] >= CPU_THRESHOLD_PERCENT
            else 0
        )
        memory_streak = (
            int(old.get("memory_streak", 0)) + 1
            if row["rss_bytes"] >= MEMORY_THRESHOLD_GIB * GIB
            else 0
        )
        reasons: list[str] = []
        if (
            row["elapsed_seconds"] >= MIN_RUNTIME_SECONDS
            and cpu_streak >= CPU_STREAK_REQUIRED
            and row["ppid"] == 1
        ):
            reasons.append("sustained_cpu")
        if (
            row["elapsed_seconds"] >= MIN_RUNTIME_SECONDS
            and memory_streak >= MEMORY_STREAK_REQUIRED
            and system_pressure
            and row["ppid"] == 1
        ):
            reasons.append("memory_pressure")
        if (
            row["elapsed_seconds"] >= ORPHAN_RUNTIME_SECONDS
            and row["ppid"] == 1
            and (cpu_streak >= 2 or memory_streak >= 2)
        ):
            reasons.append("orphan_test")
        if (
            row["elapsed_seconds"] >= MAX_RUNTIME_SECONDS
            and (cpu_streak >= 2 or memory_streak >= 2)
            and row["ppid"] == 1
        ):
            reasons.append("max_runtime")

        candidate = {
            "pid": row["pid"],
            "ppid": row["ppid"],
            "path": str(path),
            "command": row["command"][:500],
            "cpu_percent": row["cpu_percent"],
            "rss_gib": round(row["rss_bytes"] / GIB, 2),
            "elapsed_seconds": row["elapsed_seconds"],
            "cpu_streak": cpu_streak,
            "memory_streak": memory_streak,
            "signal": old.get("signal"),
            "signal_time": old.get("signal_time"),
            "last_seen": now_iso(),
        }
        if reasons and STATUS_ONLY:
            candidate["reasons"] = sorted(set(reasons))
            alerts.append(candidate)
        elif reasons:
            action = terminate_process(
                row, identity, old, sorted(set(reasons))
            )
            if action["result"] != "waiting_grace":
                actions.append(action)
            if action["result"] in {"signaled", "would_signal"}:
                candidate["signal"] = action["signal"]
                candidate["signal_time"] = time.time()
        elif (
            row["cpu_percent"] >= CPU_THRESHOLD_PERCENT * 0.5
            or row["rss_bytes"] >= MEMORY_THRESHOLD_GIB * 0.5 * GIB
            or (row["ppid"] == 1 and row["elapsed_seconds"] >= ORPHAN_RUNTIME_SECONDS)
        ):
            candidate["signal"] = None
            candidate["signal_time"] = None
            alerts.append(candidate)
        else:
            candidate["signal"] = None
            candidate["signal_time"] = None
        next_candidates[identity] = candidate

    previous_history = previous.get("action_history", [])
    if not isinstance(previous_history, list):
        previous_history = []
    action_history = (previous_history + actions)[-20:]
    return {
        "time": now_iso(),
        "status": (
            "dry_run"
            if DRY_RUN
            else ("acted" if actions else "healthy")
        ),
        "cpu_percent": round(cpu_percent, 1),
        "load_average": [
            round(load_1, 2),
            round(load_5, 2),
            round(load_15, 2),
        ],
        "logical_cpus": psutil.cpu_count(logical=True),
        "memory": memory,
        "system_pressure": system_pressure,
        "candidate_count": len(alerts),
        "tracked_count": len(next_candidates),
        "candidates": next_candidates,
        "alerts": alerts[:20],
        "actions": actions,
        "last_action": (
            actions[-1] if actions else previous.get("last_action")
        ),
        "action_history": action_history,
        "policy": {
            "scope": "temporary_macho_test_processes_only",
            "cpu_threshold_percent": CPU_THRESHOLD_PERCENT,
            "memory_threshold_gib": MEMORY_THRESHOLD_GIB,
            "cpu_streak_required": CPU_STREAK_REQUIRED,
            "memory_streak_required": MEMORY_STREAK_REQUIRED,
            "min_runtime_seconds": MIN_RUNTIME_SECONDS,
            "max_runtime_seconds": MAX_RUNTIME_SECONDS,
            "orphan_runtime_seconds": ORPHAN_RUNTIME_SECONDS,
            "memory_available_percent": MEMORY_PRESSURE_AVAILABLE_PERCENT,
            "swap_pressure_gib": SWAP_PRESSURE_GIB,
            "term_grace_seconds": TERM_GRACE_SECONDS,
        },
    }


def main() -> int:
    validate_configuration()
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    lock_handle = LOCK_PATH.open("a+")
    try:
        fcntl.flock(
            lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB
        )
    except BlockingIOError:
        if VERBOSE:
            emit({"time": now_iso(), "status": "already_running"})
        return 0

    state = evaluate()
    if STATUS_ONLY or VERBOSE or state.get("actions"):
        emit(state)
    if not DRY_RUN and not STATUS_ONLY:
        save_json(STATE_PATH, state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
