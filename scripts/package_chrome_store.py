#!/usr/bin/env python3
"""Build a deterministic first-upload Chrome Web Store package."""

from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXTENSION_DIR = ROOT / "chrome-extension"
OUTPUT = ROOT / "disk-guard-chrome-store-0.2.0.zip"
ZIP_TIMESTAMP = (2026, 1, 1, 0, 0, 0)


def add_bytes(
    archive: zipfile.ZipFile, name: str, payload: bytes
) -> None:
    entry = zipfile.ZipInfo(name, ZIP_TIMESTAMP)
    entry.compress_type = zipfile.ZIP_DEFLATED
    entry.external_attr = 0o100644 << 16
    archive.writestr(entry, payload, compresslevel=9)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a first-upload Chrome Web Store ZIP."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=OUTPUT,
        help=f"Output ZIP path (default: {OUTPUT.name})",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output = args.output.expanduser().resolve()
    checksum = output.with_name(output.name + ".sha256")
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest_path = EXTENSION_DIR / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest.pop("key", None)
    manifest_payload = (
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    ).encode()

    files = sorted(
        path
        for path in EXTENSION_DIR.rglob("*")
        if path.is_file()
        and path.name not in {".DS_Store", "manifest.json"}
    )
    with zipfile.ZipFile(output, "w") as archive:
        add_bytes(archive, "manifest.json", manifest_payload)
        for path in files:
            add_bytes(
                archive,
                path.relative_to(EXTENSION_DIR).as_posix(),
                path.read_bytes(),
            )

    with zipfile.ZipFile(output) as archive:
        packaged_manifest = json.loads(archive.read("manifest.json"))
        assert packaged_manifest["version"] == "0.2.0"
        assert "key" not in packaged_manifest
        assert archive.namelist()[0] == "manifest.json"
        assert not any(
            name.startswith("chrome-extension/")
            for name in archive.namelist()
        )

    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    checksum.write_text(f"{digest}  {output.name}\n")
    print(f"{output.name} {output.stat().st_size} {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
