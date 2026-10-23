"""Verify Action pins and run checksum-pinned actionlint; --offline uses a cached archive."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
import tarfile
import zipfile
from pathlib import Path

from snapshot import SnapshotError, require
from sync_upstream import download

ROOT = Path(__file__).resolve().parents[1]


def check_pins(root: Path = ROOT) -> int:
    pins = json.loads((root / ".github/action-pins.json").read_bytes())["actions"]
    count = 0
    for path in (root / ".github/workflows").glob("*.yml"):
        text = path.read_text(encoding="utf-8")
        require("pull_request_target" not in text and "workflow_run:" not in text, "unsafe workflow trigger")
        for action, sha in re.findall(r"^\s+uses:\s+([^@\s]+)@([^\s#]+)", text, re.M):
            require(action in pins and sha == pins[action]["sha"] and re.fullmatch(r"[0-9a-f]{40}", sha) is not None,
                    f"unreviewed/unpinned Action in {path.name}: {action}@{sha}")
            count += 1
    require(count > 0, "no workflow Actions found")
    return count


def actionlint_binary(offline: bool) -> Path:
    config = json.loads((ROOT / ".github/action-pins.json").read_bytes())["actionlint"]
    require(platform.machine().lower() in {"amd64", "x86_64"}, "actionlint bootstrap currently supports x64 Windows/Linux")
    system = "windows_amd64" if os.name == "nt" else "linux_amd64"
    require(os.name == "nt" or platform.system() == "Linux", "unsupported actionlint platform")
    pin = config[system]
    version = config["version"]
    name = f"actionlint_{version}_{system}.{pin['extension']}"
    cache = ROOT / ".cache" / "tools"
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / name
    if not archive.exists():
        require(not offline, f"missing cached actionlint archive: {name}")
        download(f"https://github.com/rhysd/actionlint/releases/download/v{version}/{name}", archive)
    require(hashlib.sha256(archive.read_bytes()).hexdigest() == pin["sha256"], "actionlint archive checksum mismatch")
    binary = cache / ("actionlint.exe" if os.name == "nt" else "actionlint")
    if os.name == "nt":
        with zipfile.ZipFile(archive) as source:
            data = source.read("actionlint.exe")
    else:
        with tarfile.open(archive, "r:gz") as source:
            member = source.extractfile("actionlint")
            require(member is not None, "actionlint executable missing")
            with member:
                data = member.read()
    binary.write_bytes(data)
    binary.chmod(0o755)
    return binary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    try:
        count = check_pins()
        binary = actionlint_binary(args.offline)
        # Built-in YAML/expression/Action checks are identical on Windows and Linux.
        # Shell snippets only invoke Python and use quoted environment variables.
        subprocess.run([str(binary), "-shellcheck=", "-pyflakes=", *[
            str(p) for p in sorted((ROOT / ".github/workflows").glob("*.yml"))]], cwd=ROOT, check=True)
        print(f"PASS: actionlint and {count} full-commit Action pins")
        return 0
    except (SnapshotError, OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"ERROR: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
