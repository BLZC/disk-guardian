#!/usr/bin/env python3
"""Canonical allowlist and safety checks for rebuildable artifacts."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
# Security: callers use fixed absolute system binaries with shell disabled.
import subprocess  # nosec B404
import time
from pathlib import Path
from typing import Any, Iterable, Optional


GIB = 1024**3
MIB = 1024**2
MIN_AGE_SECONDS = max(
    3600,
    int(os.environ.get("DISK_GUARDIAN_MIN_AGE_SECONDS", "3600")),
)
SHARED_CACHE_QUIET_SECONDS = max(
    300,
    int(
        os.environ.get(
            "DISK_GUARDIAN_CACHE_QUIET_SECONDS", "300"
        )
    ),
)

HOME = Path.home().resolve()
DATA_VOLUME = Path("/System/Volumes/Data")
PRIVATE_TMP = Path("/private/tmp").resolve()
GOCACHE = (HOME / ".cache/codex-go-build").resolve()

GO_TEMP_RE = re.compile(r"^(?:go-build\d+|go-link-?\d+)$")
TEST_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*\.test$")
ISOLATED_CACHE_RE = re.compile(
    r"^(?=[A-Za-z0-9._-]*(?:gocache|go-cache|cache))"
    r"(?:pre-submit|pre_submit|codex)"
    r"[A-Za-z0-9._-]*$"
)
HEX_BUCKET_RE = re.compile(r"^[0-9a-f]{2}$")
GO_CACHE_ENTRY_RE = re.compile(r"^[0-9a-f]{64}-[ad]$")
BUILD_RE = re.compile(
    r"(?:^|\s)(?:/\S*/)?"
    r"(?:go|compile|link|vet|ld|dsymutil|clang|clang\+\+)"
    r"(?:\s|$)|/go-build[^/\s]*/.*\.test(?:\s|$)"
)
MACHO_MAGICS = {
    bytes.fromhex("cffaedfe"),
    bytes.fromhex("feedfacf"),
    bytes.fromhex("cafebabe"),
    bytes.fromhex("bebafeca"),
}
GO_CACHE_README_PREFIX = (
    "This directory holds cached build artifacts from the Go build system."
)


def free_bytes() -> int:
    return shutil.disk_usage(DATA_VOLUME).free


def gib(value: int) -> float:
    return round(value / GIB, 2)


def run_text(
    args: list[str], timeout: float = 8
) -> tuple[int, str, str]:
    try:
        result = subprocess.run(  # nosec B603
            args,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.returncode, result.stdout, result.stderr
    except (OSError, subprocess.TimeoutExpired) as error:
        return 1, "", str(error)


def darwin_temp_dir() -> Optional[Path]:
    rc, output, _ = run_text(
        ["/usr/bin/getconf", "DARWIN_USER_TEMP_DIR"], timeout=3
    )
    if rc != 0 or not output.strip():
        return None
    try:
        path = Path(output.strip()).resolve(strict=True)
        if path.is_dir() and path.stat().st_uid == os.getuid():
            return path
    except OSError:
        pass
    return None


def process_snapshot() -> Optional[list[dict[str, Any]]]:
    rc, output, _ = run_text(
        ["/bin/ps", "-axo", "pid=,command="], timeout=5
    )
    if rc != 0:
        return None
    results: list[dict[str, Any]] = []
    for line in output.splitlines():
        stripped = line.strip()
        pid_text, separator, command = stripped.partition(" ")
        if (
            not separator
            or not pid_text.isdigit()
            or int(pid_text) == os.getpid()
        ):
            continue
        if BUILD_RE.search(command):
            results.append(
                {"pid": int(pid_text), "command": command[:500]}
            )
    return results


def process_mentions(path: Path) -> bool:
    rc, output, _ = run_text(
        ["/bin/ps", "-axo", "pid=,command="], timeout=5
    )
    if rc != 0:
        return True
    needle = str(path)
    for line in output.splitlines():
        stripped = line.strip()
        pid_text, separator, command = stripped.partition(" ")
        if (
            separator
            and pid_text.isdigit()
            and int(pid_text) != os.getpid()
            and needle in command
        ):
            return True
    return False


def open_paths() -> Optional[set[str]]:
    rc, output, _ = run_text(
        ["/usr/sbin/lsof", "-nP", "-Fn"], timeout=15
    )
    if rc != 0:
        return None
    return {
        line[1:].removesuffix(" (deleted)")
        for line in output.splitlines()
        if line.startswith("n/")
    }


def path_is_open(path: Path, opened: Optional[Iterable[str]]) -> bool:
    if opened is None:
        return True
    target = str(path)
    prefix = target + os.sep
    return any(
        candidate == target or candidate.startswith(prefix)
        for candidate in opened
    )


def is_direct_child(path: Path, root: Path) -> bool:
    try:
        return path.parent.resolve(strict=True) == root
    except OSError:
        return False


def owned_direct_path(
    path: Path, root: Path, expected_kind: str
) -> bool:
    try:
        stat = path.lstat()
        real = path.resolve(strict=True)
    except OSError:
        return False
    if (
        stat.st_uid != os.getuid()
        or path.is_symlink()
        or not is_direct_child(path, root)
        or real.parent != root
    ):
        return False
    if expected_kind == "file":
        return path.is_file()
    return path.is_dir()


def old_enough(path: Path) -> bool:
    try:
        return (
            time.time() - path.stat().st_mtime >= MIN_AGE_SECONDS
        )
    except OSError:
        return False


def is_macho(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            return handle.read(4) in MACHO_MAGICS
    except OSError:
        return False


def is_go_cache_bucket(path: Path) -> bool:
    try:
        if (
            path.is_symlink()
            or not path.is_dir()
            or path.stat().st_uid != os.getuid()
            or HEX_BUCKET_RE.fullmatch(path.name) is None
        ):
            return False
        return all(
            not entry.is_symlink()
            and entry.is_file()
            and entry.stat().st_uid == os.getuid()
            and GO_CACHE_ENTRY_RE.fullmatch(entry.name) is not None
            for entry in path.iterdir()
        )
    except OSError:
        return False


def is_go_cache_tree(path: Path) -> bool:
    """Recognize an isolated Go content-addressed cache."""
    saw_bucket = False
    try:
        if not old_enough(path):
            return False
        for child in path.iterdir():
            if child.is_symlink():
                return False
            if child.is_dir():
                if not old_enough(child) or not is_go_cache_bucket(child):
                    return False
                if any(
                    not old_enough(entry) for entry in child.iterdir()
                ):
                    return False
                saw_bucket = True
            elif child.name not in {
                "README",
                "trim.txt",
                "testexpire.txt",
            } or child.stat().st_uid != os.getuid() or not old_enough(
                child
            ):
                return False
    except OSError:
        return False
    return saw_bucket


def is_safe_go_temp_tree(path: Path) -> bool:
    """Reject links, Git metadata and foreign-owned content."""
    try:
        if (
            path.is_symlink()
            or not path.is_dir()
            or path.stat().st_uid != os.getuid()
            or not old_enough(path)
        ):
            return False
        for current, directories, files in os.walk(
            path, followlinks=False
        ):
            if ".git" in directories or ".git" in files:
                return False
            current_path = Path(current)
            for name in directories + files:
                child = current_path / name
                if (
                    child.is_symlink()
                    or child.lstat().st_uid != os.getuid()
                    or not old_enough(child)
                ):
                    return False
        return True
    except OSError:
        return False


def is_shared_go_cache_root(path: Path) -> bool:
    """Validate the configured shared cache without traversing every file."""
    try:
        stat = path.lstat()
        readme = path / "README"
        if (
            not path.is_dir()
            or path.is_symlink()
            or stat.st_uid != os.getuid()
            or path.resolve(strict=True) != path
            or not readme.is_file()
            or readme.is_symlink()
            or readme.stat().st_uid != os.getuid()
        ):
            return False
        if not readme.read_text(errors="replace").startswith(
            GO_CACHE_README_PREFIX
        ):
            return False
        saw_bucket = False
        for child in path.iterdir():
            if child.is_symlink():
                return False
            if child.is_dir():
                if (
                    child.stat().st_uid != os.getuid()
                    or HEX_BUCKET_RE.fullmatch(child.name) is None
                ):
                    return False
                saw_bucket = True
            elif child.name not in {
                "README",
                "trim.txt",
                "testexpire.txt",
            } or child.stat().st_uid != os.getuid():
                return False
        return saw_bucket
    except OSError:
        return False


def du_bytes(path: Path, timeout: float = 30) -> Optional[int]:
    if not path.exists():
        return 0
    rc, output, _ = run_text(
        ["/usr/bin/du", "-sk", str(path)], timeout=timeout
    )
    if rc != 0:
        return None
    try:
        return int(output.split()[0]) * 1024
    except (IndexError, ValueError):
        return None


def fingerprint(path: Path, child_count: int = -1) -> str:
    stat = path.lstat()
    value = (
        f"{stat.st_dev}:{stat.st_ino}:{stat.st_uid}:{stat.st_mode}:"
        f"{stat.st_size}:{stat.st_mtime_ns}:{child_count}"
    )
    return hashlib.sha256(value.encode()).hexdigest()


def direct_child_count(path: Path) -> int:
    try:
        return sum(1 for _ in path.iterdir())
    except OSError:
        return -1


def cache_has_been_quiet(path: Path) -> bool:
    cutoff = time.time() - SHARED_CACHE_QUIET_SECONDS
    try:
        mtimes = [path.stat().st_mtime]
        mtimes.extend(child.stat().st_mtime for child in path.iterdir())
    except OSError:
        return False
    return max(mtimes, default=0) <= cutoff
