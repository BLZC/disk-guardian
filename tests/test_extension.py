from __future__ import annotations

import base64
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXTENSION = ROOT / "chrome-extension"
EXPECTED_ID = "ccpomkognonnccbjmiapheoadpnepnde"


def extension_id(public_key: str) -> str:
    digest = hashlib.sha256(base64.b64decode(public_key)).digest()
    alphabet = "abcdefghijklmnop"
    return "".join(
        alphabet[nibble]
        for byte in digest[:16]
        for nibble in (byte >> 4, byte & 0x0F)
    )


class ExtensionManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest = json.loads(
            (EXTENSION / "manifest.json").read_text()
        )

    def test_manifest_has_fixed_expected_id(self) -> None:
        self.assertEqual(self.manifest["version"], "0.2.1")
        self.assertEqual(
            extension_id(self.manifest["key"]),
            EXPECTED_ID,
        )

    def test_manifest_uses_minimum_permissions(self) -> None:
        self.assertEqual(
            sorted(self.manifest["permissions"]),
            ["alarms", "storage"],
        )
        self.assertEqual(
            self.manifest["host_permissions"],
            ["http://127.0.0.1:18765/*"],
        )
        self.assertNotIn("content_scripts", self.manifest)
        self.assertNotIn("externally_connectable", self.manifest)

    def test_extension_calls_only_read_only_companion_endpoint(self) -> None:
        scripts = "\n".join(
            (EXTENSION / name).read_text()
            for name in ("popup.js", "service-worker.js")
        )
        self.assertIn("/api/extension/status", scripts)
        self.assertNotIn("/api/cleanup/", scripts)
        self.assertNotIn("https://", scripts)

    def test_store_package_omits_development_key(self) -> None:
        script = ROOT / "scripts/package_chrome_store.py"
        with tempfile.TemporaryDirectory() as temporary:
            package = Path(temporary) / "store.zip"
            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "--output",
                    str(package),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            with zipfile.ZipFile(package) as archive:
                manifest = json.loads(archive.read("manifest.json"))
                self.assertNotIn("key", manifest)
                self.assertEqual(manifest["version"], "0.2.1")
                self.assertEqual(archive.namelist()[0], "manifest.json")


if __name__ == "__main__":
    unittest.main()
