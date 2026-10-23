"""Read-only preparation job: sync, fully validate, seal and publish step outputs."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from snapshot import SnapshotError, require
from sync_artifact import pack_bundle
from sync_upstream import download, prepare, resolve_release

ROOT = Path(__file__).resolve().parents[1]


def prepare_job(current: Path, work: Path, archive: Path | None = None,
                tag: str | None = None, sha: str | None = None) -> dict:
    require(not work.exists(), "job work directory must be new")
    work.mkdir(parents=True)
    if archive is None:
        tag, sha = resolve_release(work)
        archive = work / "upstream.tar.gz"
        download(f"https://codeload.github.com/zenstory-ai/oh-story-claudecode/tar.gz/{sha}", archive)
    require(tag is not None and sha is not None, "offline replay requires tag and SHA")
    candidate = work / "candidate"
    change = prepare(archive, current, tag, sha, candidate)
    if not change["changed"]:
        return {"changed": False}
    # Preserve the static fingerprint before running candidate code.
    before = (candidate / "upstream-lock.json").read_bytes()
    report = work / "validation.json"
    subprocess.run([sys.executable, str(ROOT / "scripts/validate_all.py"), "--root", str(candidate),
                    "--report-file", str(report)], cwd=ROOT,
                   env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1"},
                   check=True, timeout=900)
    require((candidate / "upstream-lock.json").read_bytes() == before, "candidate lock changed during execution")
    # Revalidate bytes against the unchanged lock and the successful report before sealing.
    sha256 = pack_bundle(candidate, report, work / "snapshot.tar")
    return {"changed": True, "bundle_sha256": sha256, "release_tag": tag, "commit_sha": sha}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current", type=Path, default=ROOT)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()
    try:
        result = prepare_job(args.current.resolve(), args.work_dir.absolute())
        if args.github_output:
            with args.github_output.open("a", encoding="utf-8", newline="\n") as output:
                for key, value in result.items():
                    output.write(f"{key}={str(value).lower() if isinstance(value, bool) else value}\n")
        print(json.dumps(result, indent=2))
        if not result["changed"]:
            print("No relevant changes")
        return 0
    except (SnapshotError, OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        print(f"ERROR: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
