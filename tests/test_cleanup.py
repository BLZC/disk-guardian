from __future__ import annotations

import fcntl
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import cleanup  # noqa: E402
import cleanup_policy  # noqa: E402


MACHO_MAGIC = bytes.fromhex("cffaedfe")
VALID_CACHE_NAME = "a" * 64 + "-a"


def make_old(path: Path) -> None:
    old = time.time() - cleanup_policy.MIN_AGE_SECONDS - 60
    os.utime(path, (old, old))


def make_test_binary(path: Path) -> None:
    with path.open("wb") as handle:
        handle.write(MACHO_MAGIC)
        handle.truncate(101 * cleanup_policy.MIB)
    make_old(path)


def make_go_cache(path: Path, *, include_readme: bool = False) -> None:
    path.mkdir(parents=True)
    if include_readme:
        (path / "README").write_text(
            cleanup_policy.GO_CACHE_README_PREFIX + "\n"
        )
    bucket = path / "aa"
    bucket.mkdir()
    (bucket / VALID_CACHE_NAME).write_bytes(b"cache")
    make_old(bucket / VALID_CACHE_NAME)
    make_old(bucket)
    if include_readme:
        make_old(path / "README")
    make_old(path)


class CleanupPolicyTests(unittest.TestCase):
    def test_go_cache_tree_rejects_unknown_nested_content(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "codex-gocache"
            make_go_cache(root)
            self.assertTrue(cleanup_policy.is_go_cache_tree(root))
            (root / "aa" / "notes.txt").write_text("personal")
            self.assertFalse(cleanup_policy.is_go_cache_tree(root))

    def test_go_cache_tree_rejects_recent_nested_content(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "codex-gocache"
            make_go_cache(root)
            (root / "aa" / VALID_CACHE_NAME).touch()
            self.assertFalse(cleanup_policy.is_go_cache_tree(root))

    def test_shared_cache_requires_go_readme_marker(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = (Path(temporary) / "codex-go-build").resolve()
            make_go_cache(root, include_readme=True)
            self.assertTrue(
                cleanup_policy.is_shared_go_cache_root(root)
            )
            (root / "README").write_text("my unrelated directory")
            self.assertFalse(
                cleanup_policy.is_shared_go_cache_root(root)
            )

    def test_go_temp_tree_rejects_git_and_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve() / "go-build123"
            root.mkdir()
            (root / "artifact").write_text("generated")
            make_old(root / "artifact")
            make_old(root)
            self.assertTrue(cleanup_policy.is_safe_go_temp_tree(root))
            (root / ".git").write_text("gitdir: elsewhere")
            self.assertFalse(cleanup_policy.is_safe_go_temp_tree(root))
            (root / ".git").unlink()
            (root / "link").symlink_to(root / "artifact")
            self.assertFalse(cleanup_policy.is_safe_go_temp_tree(root))


class CleanupManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.private_tmp = self.root / "private-tmp"
        self.go_temp = self.root / "go-temp"
        self.go_cache = self.root / "codex-go-build"
        self.state = self.root / "state" / "manual.json"
        self.lock = self.root / "state" / "disk.lock"
        self.private_tmp.mkdir()
        self.go_temp.mkdir()
        make_go_cache(self.go_cache, include_readme=True)
        self.manager = cleanup.CleanupManager(
            private_tmp=self.private_tmp,
            go_temp_root=self.go_temp,
            go_cache=self.go_cache,
            state_path=self.state,
            lock_path=self.lock,
        )
        self.patches = [
            mock.patch.object(cleanup, "open_paths", return_value=set()),
            mock.patch.object(cleanup, "process_snapshot", return_value=[]),
            mock.patch.object(cleanup, "process_mentions", return_value=False),
            mock.patch.object(cleanup, "cache_has_been_quiet", return_value=True),
        ]
        for patch in self.patches:
            patch.start()

    def tearDown(self) -> None:
        for patch in reversed(self.patches):
            patch.stop()
        self.temporary.cleanup()

    def test_scan_accepts_only_allowlisted_shapes(self) -> None:
        allowed = self.private_tmp / "safe.test"
        make_test_binary(allowed)
        outside = self.private_tmp / "notes.txt"
        outside.write_text("keep me")
        make_old(outside)
        invalid_cache = self.private_tmp / "codex-cache-invalid"
        invalid_cache.mkdir()
        (invalid_cache / "personal.txt").write_text("keep me")
        make_old(invalid_cache)

        plan = self.manager.scan()
        paths = {item["path"] for item in plan["candidates"]}

        self.assertIn(str(allowed), paths)
        self.assertNotIn(str(outside), paths)
        self.assertNotIn(str(invalid_cache), paths)

    def test_execute_skips_candidate_changed_after_scan(self) -> None:
        candidate = self.private_tmp / "changed.test"
        make_test_binary(candidate)
        plan = self.manager.scan()
        selected = next(
            item
            for item in plan["candidates"]
            if item["path"] == str(candidate)
        )
        with candidate.open("ab") as handle:
            handle.write(b"changed")

        with mock.patch.object(cleanup, "free_bytes", return_value=0):
            receipt = self.manager.execute(
                plan["token"], [selected["id"]]
            )

        self.assertTrue(candidate.exists())
        self.assertEqual(receipt["deleted_count"], 0)
        self.assertEqual(
            receipt["results"][0]["reason"],
            "changed_since_scan",
        )

    def test_automatic_cleanup_stops_after_target(self) -> None:
        first = self.private_tmp / "first.test"
        second = self.private_tmp / "second.test"
        make_test_binary(first)
        make_test_binary(second)
        target = 20 * cleanup_policy.GIB

        def fake_free_bytes() -> int:
            return target if not first.exists() else 0

        with mock.patch.object(
            cleanup, "free_bytes", side_effect=fake_free_bytes
        ):
            outcome = self.manager.automatic_cleanup(target)

        self.assertFalse(first.exists())
        self.assertTrue(second.exists())
        self.assertEqual(outcome["candidate_count"], 3)
        deleted = [
            action
            for action in outcome["actions"]
            if action.get("status") == "deleted"
        ]
        self.assertEqual(len(deleted), 1)

    def test_automatic_and_manual_cleanup_share_lock(self) -> None:
        self.lock.parent.mkdir(parents=True, exist_ok=True)
        handle = self.lock.open("a+")
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            with self.assertRaisesRegex(ValueError, "cleanup_busy"):
                self.manager.automatic_cleanup(cleanup_policy.GIB)
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()

    def test_shared_cache_cleanup_preserves_identity_marker(self) -> None:
        plan = self.manager.scan()
        selected = next(
            item
            for item in plan["candidates"]
            if item["category"] == "shared_go_cache"
        )

        with mock.patch.object(cleanup, "free_bytes", return_value=0):
            receipt = self.manager.execute(
                plan["token"], [selected["id"]]
            )

        self.assertEqual(receipt["deleted_count"], 1)
        self.assertTrue(self.go_cache.exists())
        self.assertTrue((self.go_cache / "README").exists())
        self.assertFalse((self.go_cache / "aa").exists())


if __name__ == "__main__":
    unittest.main()
