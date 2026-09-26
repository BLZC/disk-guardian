#!/usr/bin/env python3
"""Two-step manual cleanup planner for verified rebuildable artifacts."""

from __future__ import annotations

import hashlib
import fcntl
import json
import os
import secrets
import shutil
import tempfile
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional, TextIO

from cleanup_policy import (
    GOCACHE,
    GO_TEMP_RE,
    ISOLATED_CACHE_RE,
    MIB,
    PRIVATE_TMP,
    TEST_RE,
    cache_has_been_quiet,
    darwin_temp_dir,
    direct_child_count,
    du_bytes,
    fingerprint,
    free_bytes,
    gib,
    is_go_cache_tree,
    is_go_cache_bucket,
    is_macho,
    is_safe_go_temp_tree,
    is_shared_go_cache_root,
    old_enough,
    open_paths,
    owned_direct_path,
    path_is_open,
    process_mentions,
    process_snapshot,
)


PLAN_TTL_SECONDS = 300
MAX_BODY_CANDIDATES = 500

HOME = Path.home().resolve()
STATE_DIR = Path(
    os.environ.get(
        "DISK_GUARDIAN_STATE_DIR",
        str(HOME / "Library/Application Support/Disk Guardian"),
    )
).resolve()
STATE_PATH = STATE_DIR / "manual_cleanup_state.json"

CATEGORY_LABELS = {
    "test_binary": "大型测试二进制",
    "isolated_go_cache": "独立 Go 缓存",
    "go_temp": "Go 临时目录",
    "shared_go_cache": "共享 Go 构建缓存",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(
        timespec="seconds"
    )


@dataclass(frozen=True)
class Candidate:
    id: str
    category: str
    label: str
    path: str
    bytes: int
    fingerprint: str
    child_count: int

    def public(self) -> dict[str, Any]:
        value = asdict(self)
        value["gib"] = gib(self.bytes)
        return value


@dataclass
class CleanupPlan:
    token: str
    created_at: float
    expires_at: float
    candidates: dict[str, Candidate]
    skipped: list[dict[str, Any]]


class CleanupManager:
    def __init__(
        self,
        *,
        private_tmp: Path = PRIVATE_TMP,
        go_temp_root: Optional[Path] = None,
        go_cache: Path = GOCACHE,
        state_path: Path = STATE_PATH,
        lock_path: Optional[Path] = None,
    ) -> None:
        self.private_tmp = private_tmp.resolve()
        self.go_temp_root = (
            go_temp_root.resolve()
            if go_temp_root is not None
            else darwin_temp_dir()
        )
        self.go_cache = go_cache.resolve()
        self.state_path = state_path
        self.lock_path = (
            lock_path
            if lock_path is not None
            else state_path.parent / "disk_guard.lock"
        )
        self._plans: dict[str, CleanupPlan] = {}
        self._lock = threading.Lock()

    def _candidate_id(
        self, category: str, path: Path, value: str
    ) -> str:
        return hashlib.sha256(
            f"{category}:{path}:{value}".encode()
        ).hexdigest()[:24]

    def _add_candidate(
        self,
        collection: dict[str, Candidate],
        category: str,
        path: Path,
        size: int,
        child_count: int = -1,
    ) -> None:
        current_fingerprint = fingerprint(path, child_count)
        candidate_id = self._candidate_id(
            category, path, current_fingerprint
        )
        collection[candidate_id] = Candidate(
            id=candidate_id,
            category=category,
            label=CATEGORY_LABELS[category],
            path=str(path),
            bytes=size,
            fingerprint=current_fingerprint,
            child_count=child_count,
        )

    def _scan_locked(self) -> CleanupPlan:
        opened = open_paths()
        builds = process_snapshot()
        candidates: dict[str, Candidate] = {}
        skipped: list[dict[str, Any]] = []

        if opened is None:
            skipped.append(
                {
                    "group": "all",
                    "reason": "open_file_check_failed",
                }
            )
        else:
            try:
                tmp_children = sorted(
                    self.private_tmp.iterdir(),
                    key=lambda item: item.name,
                )
            except OSError:
                tmp_children = []
                skipped.append(
                    {
                        "group": "private_tmp",
                        "reason": "directory_unavailable",
                    }
                )
            for path in tmp_children:
                try:
                    stat = path.stat()
                except OSError:
                    continue
                if (
                    path.is_file()
                    and TEST_RE.fullmatch(path.name)
                    and stat.st_size >= 100 * MIB
                    and old_enough(path)
                    and owned_direct_path(
                        path, self.private_tmp, "file"
                    )
                    and not path_is_open(path, opened)
                    and not process_mentions(path)
                    and is_macho(path)
                ):
                    self._add_candidate(
                        candidates,
                        "test_binary",
                        path,
                        stat.st_size,
                    )
                elif (
                    path.is_dir()
                    and ISOLATED_CACHE_RE.fullmatch(path.name)
                    and old_enough(path)
                    and owned_direct_path(
                        path, self.private_tmp, "dir"
                    )
                    and not path_is_open(path, opened)
                    and not process_mentions(path)
                    and is_go_cache_tree(path)
                ):
                    size = du_bytes(path)
                    if size is not None:
                        count = direct_child_count(path)
                        self._add_candidate(
                            candidates,
                            "isolated_go_cache",
                            path,
                            size,
                            count,
                        )

        if builds is None:
            skipped.append(
                {
                    "group": "go_build",
                    "reason": "process_check_failed",
                }
            )
        elif builds:
            skipped.append(
                {
                    "group": "go_build",
                    "reason": "active_build",
                    "count": len(builds),
                }
            )
        elif opened is not None:
            if self.go_temp_root is None:
                skipped.append(
                    {
                        "group": "go_temp",
                        "reason": "temp_root_unavailable",
                    }
                )
            else:
                try:
                    go_temp_children = sorted(
                        self.go_temp_root.iterdir(),
                        key=lambda item: item.name,
                    )
                except OSError:
                    go_temp_children = []
                for path in go_temp_children:
                    if (
                        GO_TEMP_RE.fullmatch(path.name)
                        and old_enough(path)
                        and owned_direct_path(
                            path, self.go_temp_root, "dir"
                        )
                        and not path_is_open(path, opened)
                        and not process_mentions(path)
                        and is_safe_go_temp_tree(path)
                    ):
                        size = du_bytes(path)
                        if size is not None:
                            count = direct_child_count(path)
                            self._add_candidate(
                                candidates,
                                "go_temp",
                                path,
                                size,
                                count,
                            )

            try:
                cache_stat = self.go_cache.lstat()
                cache_safe = (
                    self.go_cache.is_dir()
                    and not self.go_cache.is_symlink()
                    and cache_stat.st_uid == os.getuid()
                    and self.go_cache.resolve(strict=True)
                    == self.go_cache
                    and is_shared_go_cache_root(self.go_cache)
                )
            except OSError:
                cache_safe = False
            if (
                cache_safe
                and cache_has_been_quiet(self.go_cache)
                and not path_is_open(self.go_cache, opened)
                and not process_mentions(self.go_cache)
            ):
                size = du_bytes(self.go_cache, timeout=45)
                if size:
                    count = direct_child_count(self.go_cache)
                    self._add_candidate(
                        candidates,
                        "shared_go_cache",
                        self.go_cache,
                        size,
                        count,
                    )
            elif cache_safe:
                skipped.append(
                    {
                        "group": "shared_go_cache",
                        "reason": "active_or_not_quiet",
                    }
                )

        token = secrets.token_urlsafe(24)
        current = time.time()
        plan = CleanupPlan(
            token=token,
            created_at=current,
            expires_at=current + PLAN_TTL_SECONDS,
            candidates=candidates,
            skipped=skipped,
        )
        self._plans[token] = plan
        self._plans = {
            key: value
            for key, value in self._plans.items()
            if value.expires_at > current
        }
        return plan

    def scan(self) -> dict[str, Any]:
        with self._lock:
            plan = self._scan_locked()
            items = [
                candidate.public()
                for candidate in sorted(
                    plan.candidates.values(),
                    key=lambda item: (
                        item.category,
                        item.path,
                    ),
                )
            ]
            categories: dict[str, dict[str, Any]] = {}
            for item in items:
                category = categories.setdefault(
                    item["category"],
                    {
                        "category": item["category"],
                        "label": item["label"],
                        "count": 0,
                        "bytes": 0,
                        "gib": 0,
                        "ids": [],
                    },
                )
                category["count"] += 1
                category["bytes"] += item["bytes"]
                category["ids"].append(item["id"])
            for category in categories.values():
                category["gib"] = gib(category["bytes"])
            total = sum(item["bytes"] for item in items)
            return {
                "token": plan.token,
                "created_at": datetime.fromtimestamp(
                    plan.created_at, timezone.utc
                )
                .astimezone()
                .isoformat(timespec="seconds"),
                "expires_at": datetime.fromtimestamp(
                    plan.expires_at, timezone.utc
                )
                .astimezone()
                .isoformat(timespec="seconds"),
                "total_bytes": total,
                "total_gib": gib(total),
                "candidate_count": len(items),
                "categories": list(categories.values()),
                "candidates": items,
                "skipped": plan.skipped,
            }

    def _candidate_unchanged(
        self, candidate: Candidate
    ) -> tuple[bool, str]:
        path = Path(candidate.path)
        try:
            expected_kind = (
                "file"
                if candidate.category == "test_binary"
                else "dir"
            )
            root = (
                self.private_tmp
                if candidate.category
                in {"test_binary", "isolated_go_cache"}
                else self.go_temp_root
                if candidate.category == "go_temp"
                else path
            )
            if candidate.category == "shared_go_cache":
                if (
                    path != self.go_cache
                    or not is_shared_go_cache_root(path)
                ):
                    return False, "root_safety"
            elif root is None or not owned_direct_path(
                path, root, expected_kind
            ):
                return False, "path_safety"
            count = (
                direct_child_count(path)
                if candidate.child_count >= 0
                else -1
            )
            if fingerprint(path, count) != candidate.fingerprint:
                return False, "changed_since_scan"
            current_size = (
                path.stat().st_size
                if candidate.category == "test_binary"
                else du_bytes(
                    path,
                    timeout=45
                    if candidate.category == "shared_go_cache"
                    else 30,
                )
            )
            if (
                current_size is None
                or current_size != candidate.bytes
            ):
                return False, "size_changed_since_scan"
            if process_mentions(path):
                return False, "process_reference"
            opened = open_paths()
            if opened is None or path_is_open(path, opened):
                return False, "open_or_check_failed"
            if candidate.category == "test_binary" and not is_macho(
                path
            ):
                return False, "format_changed"
            if (
                candidate.category == "isolated_go_cache"
                and not is_go_cache_tree(path)
            ):
                return False, "structure_changed"
            if (
                candidate.category == "go_temp"
                and not is_safe_go_temp_tree(path)
            ):
                return False, "structure_changed"
            if (
                candidate.category == "shared_go_cache"
                and not cache_has_been_quiet(path)
            ):
                return False, "cache_not_quiet"
            return True, "verified"
        except OSError:
            return False, "missing_or_unavailable"

    def _remove_candidate(
        self,
        candidate: Candidate,
        should_stop: Optional[Callable[[], bool]] = None,
    ) -> dict[str, Any]:
        path = Path(candidate.path)
        if candidate.category == "shared_go_cache":
            removed = 0
            for child in sorted(
                path.iterdir(), key=lambda item: item.name
            ):
                if should_stop is not None and should_stop():
                    return {
                        "id": candidate.id,
                        "path": candidate.path,
                        "status": "partial",
                        "reason": "target_reached",
                        "removed_entries": removed,
                    }
                builds = process_snapshot()
                opened = open_paths()
                if (
                    builds is None
                    or builds
                    or opened is None
                    or path_is_open(child, opened)
                    or process_mentions(child)
                ):
                    return {
                        "id": candidate.id,
                        "path": candidate.path,
                        "status": "partial",
                        "reason": "build_or_open_file_started",
                        "removed_entries": removed,
                    }
                if child.is_symlink():
                    continue
                if child.is_file() and child.name in {
                    "README",
                    "trim.txt",
                    "testexpire.txt",
                }:
                    continue
                if child.is_dir() and not is_go_cache_bucket(child):
                    return {
                        "id": candidate.id,
                        "path": candidate.path,
                        "status": "partial",
                        "reason": "cache_structure_changed",
                        "removed_entries": removed,
                    }
                if child.is_file():
                    return {
                        "id": candidate.id,
                        "path": candidate.path,
                        "status": "partial",
                        "reason": "cache_structure_changed",
                        "removed_entries": removed,
                    }
                if child.is_dir():
                    shutil.rmtree(child)
                elif child.is_file():
                    child.unlink()
                else:
                    return {
                        "id": candidate.id,
                        "path": candidate.path,
                        "status": "partial",
                        "reason": "cache_structure_changed",
                        "removed_entries": removed,
                    }
                removed += 1
            return {
                "id": candidate.id,
                "path": candidate.path,
                "status": "deleted",
                "removed_entries": removed,
            }
        if candidate.category == "test_binary":
            path.unlink()
        else:
            shutil.rmtree(path)
        return {
            "id": candidate.id,
            "path": candidate.path,
            "status": "deleted",
        }

    def _acquire_disk_lock(self) -> TextIO:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_handle = self.lock_path.open("a+")
        try:
            fcntl.flock(
                lock_handle.fileno(),
                fcntl.LOCK_EX | fcntl.LOCK_NB,
            )
        except BlockingIOError:
            lock_handle.close()
            raise ValueError("cleanup_busy")
        return lock_handle

    @staticmethod
    def _release_disk_lock(lock_handle: TextIO) -> None:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
        lock_handle.close()

    def execute(
        self, token: str, selected_ids: list[str]
    ) -> dict[str, Any]:
        with self._lock:
            lock_handle = self._acquire_disk_lock()
            try:
                return self._execute_locked(token, selected_ids)
            finally:
                self._release_disk_lock(lock_handle)

    def _execute_locked(
        self, token: str, selected_ids: list[str]
    ) -> dict[str, Any]:
        before = free_bytes()
        current = time.time()
        plan = self._plans.pop(token, None)
        if plan is None:
            raise ValueError("cleanup_plan_not_found")
        if plan.expires_at <= current:
            raise ValueError("cleanup_plan_expired")
        unique_ids = list(dict.fromkeys(selected_ids))
        if (
            not unique_ids
            or len(unique_ids) > MAX_BODY_CANDIDATES
            or any(
                candidate_id not in plan.candidates
                for candidate_id in unique_ids
            )
        ):
            raise ValueError("invalid_candidate_selection")

        results: list[dict[str, Any]] = []
        deleted_bytes = 0
        for candidate_id in unique_ids:
            candidate = plan.candidates[candidate_id]
            active_builds = process_snapshot()
            if (
                candidate.category
                in {"go_temp", "shared_go_cache"}
                and (active_builds is None or active_builds)
            ):
                results.append(
                    {
                        "id": candidate.id,
                        "path": candidate.path,
                        "status": "skipped",
                        "reason": "active_build",
                    }
                )
                continue
            verified, reason = self._candidate_unchanged(
                candidate
            )
            if not verified:
                results.append(
                    {
                        "id": candidate.id,
                        "path": candidate.path,
                        "status": "skipped",
                        "reason": reason,
                    }
                )
                continue
            try:
                result = self._remove_candidate(candidate)
                results.append(result)
                if result["status"] == "deleted":
                    deleted_bytes += candidate.bytes
            except OSError as error:
                results.append(
                    {
                        "id": candidate.id,
                        "path": candidate.path,
                        "status": "error",
                        "reason": str(error),
                    }
                )

        after = free_bytes()
        receipt = {
            "time": now_iso(),
            "before_free_gib": gib(before),
            "after_free_gib": gib(after),
            "reclaimed_gib": gib(max(0, after - before)),
            "estimated_deleted_gib": gib(deleted_bytes),
            "selected_count": len(unique_ids),
            "deleted_count": sum(
                result["status"] == "deleted"
                for result in results
            ),
            "skipped_count": sum(
                result["status"] in {"skipped", "partial"}
                for result in results
            ),
            "error_count": sum(
                result["status"] == "error"
                for result in results
            ),
            "results": results,
        }
        self._save_receipt(receipt)
        return receipt

    def automatic_cleanup(
        self,
        target_free_bytes: int,
        *,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Clean verified candidates in a fixed order until the target."""
        if target_free_bytes <= 0:
            raise ValueError("invalid_target")
        before = free_bytes()
        with self._lock:
            lock_handle = self._acquire_disk_lock()
            try:
                plan = self._scan_locked()
                self._plans.pop(plan.token, None)
                priority = {
                    "test_binary": 0,
                    "isolated_go_cache": 1,
                    "go_temp": 2,
                    "shared_go_cache": 3,
                }
                candidates = sorted(
                    plan.candidates.values(),
                    key=lambda item: (
                        priority.get(item.category, 99),
                        item.path,
                    ),
                )
                results: list[dict[str, Any]] = [
                    {
                        "kind": "skip",
                        "path": item.get("group", "unknown"),
                        "reason": item.get("reason", "unknown"),
                        **(
                            {"count": item["count"]}
                            if "count" in item
                            else {}
                        ),
                    }
                    for item in plan.skipped
                ]
                estimated_deleted_bytes = 0
                for candidate in candidates:
                    if not dry_run and free_bytes() >= target_free_bytes:
                        break
                    active_builds = process_snapshot()
                    if (
                        candidate.category
                        in {"go_temp", "shared_go_cache"}
                        and (active_builds is None or active_builds)
                    ):
                        results.append(
                            {
                                "kind": "skip",
                                "path": candidate.path,
                                "reason": "active_build",
                            }
                        )
                        continue
                    verified, reason = self._candidate_unchanged(
                        candidate
                    )
                    if not verified:
                        results.append(
                            {
                                "kind": "skip",
                                "path": candidate.path,
                                "reason": reason,
                            }
                        )
                        continue
                    if dry_run:
                        results.append(
                            {
                                "kind": candidate.category,
                                "path": candidate.path,
                                "bytes": candidate.bytes,
                                "status": "would_delete",
                            }
                        )
                        estimated_deleted_bytes += candidate.bytes
                        continue
                    try:
                        result = self._remove_candidate(
                            candidate,
                            should_stop=(
                                lambda: free_bytes()
                                >= target_free_bytes
                            ),
                        )
                    except OSError as error:
                        results.append(
                            {
                                "kind": "error",
                                "path": candidate.path,
                                "reason": str(error),
                            }
                        )
                        continue
                    results.append(
                        {
                            "kind": (
                                candidate.category
                                if result["status"] == "deleted"
                                else "skip"
                            ),
                            "path": candidate.path,
                            "status": result["status"],
                            **(
                                {"reason": result["reason"]}
                                if "reason" in result
                                else {}
                            ),
                            **(
                                {
                                    "removed_entries":
                                    result["removed_entries"]
                                }
                                if "removed_entries" in result
                                else {}
                            ),
                        }
                    )
                    if result["status"] == "deleted":
                        estimated_deleted_bytes += candidate.bytes
                after = free_bytes()
                return {
                    "before_free_gib": gib(before),
                    "after_free_gib": gib(after),
                    "reclaimed_gib": gib(max(0, after - before)),
                    "estimated_deleted_gib": gib(
                        estimated_deleted_bytes
                    ),
                    "candidate_count": len(candidates),
                    "dry_run": dry_run,
                    "actions": results,
                }
            finally:
                self._release_disk_lock(lock_handle)

    def _save_receipt(self, receipt: dict[str, Any]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(
            prefix=f".{self.state_path.name}.",
            dir=str(self.state_path.parent),
        )
        try:
            with os.fdopen(descriptor, "w") as handle:
                json.dump(
                    receipt,
                    handle,
                    ensure_ascii=False,
                    sort_keys=True,
                )
                handle.write("\n")
            os.replace(temporary, self.state_path)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass

    def latest(self) -> Optional[dict[str, Any]]:
        try:
            value = json.loads(self.state_path.read_text())
            return value if isinstance(value, dict) else None
        except (OSError, json.JSONDecodeError):
            return None
