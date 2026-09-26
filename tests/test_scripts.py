from __future__ import annotations

import hashlib
import json
import os
import plistlib
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "scripts/install.sh"
UNINSTALLER = ROOT / "scripts/uninstall.sh"
RELEASE_FILES = (
    "server.py",
    "system_metrics.py",
    "cleanup.py",
    "cleanup_policy.py",
    "requirements.txt",
    "companion/disk_guard.py",
    "companion/resource_guard.py",
    "dist/index.html",
    "dist/app.js",
    "dist/styles.css",
)


def release_id() -> str:
    lines = []
    for relative in RELEASE_FILES:
        digest = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        lines.append(f"{digest}  {relative}\n")
    digest = hashlib.sha256("".join(lines).encode()).hexdigest()
    return f"0.2.1-{digest[:12]}"


class ScriptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.home = self.root / "home"
        self.install = self.root / "install"
        self.state = self.root / "state"
        self.logs = self.root / "logs"
        self.agents = self.root / "agents"
        self.home.mkdir()
        self.environment = {
            **os.environ,
            "HOME": str(self.home),
            "DISK_GUARDIAN_INSTALL_DIR": str(self.install),
            "DISK_GUARDIAN_STATE_DIR": str(self.state),
            "DISK_GUARDIAN_LOG_DIR": str(self.logs),
            "DISK_GUARDIAN_LAUNCH_AGENT_DIR": str(self.agents),
        }

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_script(
        self, script: Path, *args: str
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(script), *args],
            cwd=ROOT,
            env=self.environment,
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )

    def seed_valid_release(self) -> str:
        identity = release_id()
        release = self.install / "releases" / identity
        for relative in RELEASE_FILES:
            destination = release / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / relative, destination)
        python = release / "venv/bin/python"
        python.parent.mkdir(parents=True)
        python.write_text(
            "#!/bin/bash\n"
            "if test \"$1\" = \"-c\"; then exit 0; fi\n"
            "case \"$1\" in\n"
            "  */companion/disk_guard.py|*/companion/resource_guard.py)\n"
            "    test \"${2:-}\" = \"--status\" && exit 0\n"
            "    ;;\n"
            "esac\n"
            "exec /usr/bin/python3 \"$@\"\n"
        )
        python.chmod(0o755)
        self.install.mkdir(exist_ok=True)
        (self.install / ".disk-guardian-install").write_text(
            "disk-guardian\n"
        )
        return identity

    def test_installer_reuses_valid_release_and_preserves_config(self) -> None:
        identity = self.seed_valid_release()
        old_release = self.install / "releases/old-release"
        old_release.mkdir()
        (self.install / "current").symlink_to("releases/old-release")
        (self.install / "install.json").write_text(
            json.dumps(
                {
                    "extension_id": (
                        "ccpomkognonnccbjmiapheoadpnepnde"
                    ),
                    "threshold_gib": 11,
                    "target_gib": 23,
                }
            )
        )

        result = self.run_script(INSTALLER, "--no-load")

        self.assertEqual(result.returncode, 0, result.stderr)
        config = json.loads(
            (self.install / "install.json").read_text()
        )
        self.assertEqual(config["release_id"], identity)
        self.assertEqual(config["version"], "0.2.1")
        self.assertEqual(config["threshold_gib"], 11)
        self.assertEqual(config["target_gib"], 23)
        self.assertEqual(
            sorted(
                path.name
                for path in (self.install / "releases").iterdir()
            ),
            [identity, "old-release"],
        )
        self.assertEqual(
            (self.install / "current").resolve().name,
            identity,
        )
        dashboard = plistlib.loads(
            (
                self.agents
                / "io.github.blzc.disk-guardian.dashboard.plist"
            ).read_bytes()
        )
        self.assertIn(
            str(self.install / "releases" / identity),
            dashboard["ProgramArguments"][0],
        )

        repeated = self.run_script(INSTALLER, "--no-load")

        self.assertEqual(repeated.returncode, 0, repeated.stderr)
        self.assertEqual(
            sorted(
                path.name
                for path in (self.install / "releases").iterdir()
            ),
            [identity, "old-release"],
        )

    def test_installer_rejects_non_product_directory(self) -> None:
        self.install.mkdir()
        (self.install / "personal.txt").write_text("keep")

        result = self.run_script(INSTALLER, "--no-load")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("不属于 Disk Guardian", result.stderr)
        self.assertTrue((self.install / "personal.txt").exists())

    def test_installer_rejects_invalid_product_marker(self) -> None:
        self.install.mkdir()
        (self.install / ".disk-guardian-install").write_text(
            "another-product\n"
        )
        (self.install / "personal.txt").write_text("keep")

        result = self.run_script(INSTALLER, "--no-load")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("产品目录标记无效", result.stderr)
        self.assertTrue((self.install / "personal.txt").exists())

    def test_installer_rejects_overlapping_product_directories(self) -> None:
        self.environment["DISK_GUARDIAN_STATE_DIR"] = str(
            self.install / "state"
        )

        result = self.run_script(INSTALLER, "--no-load")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("嵌套", result.stderr)

    def test_uninstaller_rejects_non_product_directory(self) -> None:
        self.install.mkdir()
        (self.install / "personal.txt").write_text("keep")

        result = self.run_script(UNINSTALLER, "--purge-data")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("拒绝删除", result.stderr)
        self.assertTrue((self.install / "personal.txt").exists())


if __name__ == "__main__":
    unittest.main()
