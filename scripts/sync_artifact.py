"""Seal/read sync artifacts and apply only allowed paths. Never execute candidate code."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import subprocess
import tarfile
import tempfile
from pathlib import Path

from snapshot import (HASH_RE, PATHS, SHA_RE, SnapshotError, allowed_file, compare,
                      inventory, plain_directory, portable_key, regular_file, require, safe_path, write_json)
from validate_all import validate_distribution_data
from validate_layout import validate_layout
from validate_references import validate_references

MAX_BUNDLE = 64 * 1024 * 1024
MAX_FILE = 8 * 1024 * 1024
REPLACE_PATHS = (*PATHS, "LICENSE", "upstream-lock.json")


def bundle_digest(path: Path) -> str:
    require(path.is_file() and regular_file(path), "bundle must be a regular file")
    require(path.stat().st_size <= MAX_BUNDLE, "bundle exceeds size limit")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_report(root: Path, report: dict) -> dict:
    require(isinstance(report, dict), "validation report must be an object")
    layout = validate_layout(root)
    references = validate_references(root)
    validate_distribution_data(root)
    require(report.get("schema_version") == 1 and report.get("status") == "passed", "missing successful validation report")
    require(report.get("layout") == layout, "validation report snapshot mismatch")
    require(report.get("references") == references, "validation report dependencies mismatch")
    files = inventory(root)
    syntax = {"python": sum(p.endswith(".py") for p in files),
              "javascript": sum(p.endswith(".js") for p in files)}
    require(report.get("syntax") == syntax, "validation report syntax coverage mismatch")
    require(report.get("samples") == {"cli_cases": 12, "report_only_unchanged": True}, "detector checks missing")
    require(report.get("runtime", {}).get("synthetic_cli_cases") == 10, "runtime smoke checks missing")
    tests = report.get("unit_tests", {})
    require(tests.get("status") == "passed" and type(tests.get("count")) is int and tests["count"] > 0,
            "unit tests must have passed before sealing")
    return layout


def pack_bundle(root: Path, report_path: Path, output: Path) -> str:
    report = json.loads(report_path.read_bytes())
    check_report(root, report)
    files = {"snapshot/" + p: data for p, data in inventory(root).items()}
    for name in ("LICENSE", "upstream-lock.json"):
        files["snapshot/" + name] = (root / name).read_bytes()
    files["validation.json"] = report_path.read_bytes()
    require(not output.exists(), "bundle output must be new")
    with output.open("xb") as stream, tarfile.open(fileobj=stream, mode="w") as archive:
        for path, data in sorted(files.items()):
            item = tarfile.TarInfo(path)
            item.size = len(data)
            item.mode = 0o644
            item.mtime = 0
            archive.addfile(item, io.BytesIO(data))
    return bundle_digest(output)


def unpack_bundle(artifact: Path, expected_digest: str, destination: Path) -> tuple[Path, dict]:
    require(HASH_RE.fullmatch(expected_digest) is not None, "expected a full SHA-256 bundle digest")
    require(bundle_digest(artifact) == expected_digest, "bundle SHA-256 mismatch")
    require(not destination.exists(), "unpack destination must be new")
    files: dict[str, bytes] = {}
    seen: set[str] = set()
    total = 0
    with tarfile.open(artifact, "r:") as archive:
        for index, member in enumerate(archive, 1):
            require(index <= 10000, "too many bundle entries")
            safe_path(member.name)
            key = portable_key(member.name)
            require(key not in seen, "duplicate/colliding bundle path")
            seen.add(key)
            require(member.isfile(), "bundle links/directories/special files forbidden")
            name = member.name
            if name != "validation.json":
                require(name.startswith("snapshot/"), "unexpected bundle path")
                relative = name.removeprefix("snapshot/")
                require(allowed_file(relative) or relative == "upstream-lock.json", f"forbidden bundle path: {name}")
            require(0 <= member.size <= MAX_FILE, "oversized bundle member")
            total += member.size
            require(total <= MAX_BUNDLE, "unpacked bundle exceeds size limit")
            reader = archive.extractfile(member)
            require(reader is not None, "unreadable bundle member")
            with reader:
                files[name] = reader.read(MAX_FILE + 1)
            require(len(files[name]) == member.size, "truncated bundle member")
    require("validation.json" in files, "bundle missing validation report")
    # No tar extract APIs: only checked regular paths are materialized.
    destination.mkdir()
    for name, data in files.items():
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    root = destination / "snapshot"
    report = json.loads(files["validation.json"])
    check_report(root, report)
    expected_paths = {"snapshot/" + p for p in inventory(root)} | {
        "snapshot/LICENSE", "snapshot/upstream-lock.json", "validation.json"}
    require(set(files) == expected_paths, "bundle has extra/missing files")
    return root, report


def verify_checkout(root: Path, expected_sha: str) -> None:
    require(SHA_RE.fullmatch(expected_sha) is not None, "invalid expected base SHA")
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True).stdout.strip()
    require(head == expected_sha, "default branch advanced; rerun synchronization on its new HEAD")
    status = subprocess.run(["git", "status", "--porcelain=v1", "--untracked-files=all"],
                            cwd=root, check=True, capture_output=True, text=True).stdout
    require(not status.strip(), "write-job checkout must be clean before applying bundle")


def pr_metadata(current: Path, candidate: Path, report: dict, changes: dict, base_sha: str) -> tuple[str, str]:
    lock = json.loads((candidate / "upstream-lock.json").read_bytes())
    old = json.loads((current / "upstream-lock.json").read_bytes())
    title = f"chore(sync): Oh Story {lock['release_tag']} writing/deslop skills"
    lines = [f"Update the two complete Skill subtrees from Oh Story `{old['release_tag']}` to `{lock['release_tag']}`.",
             "", f"- Upstream: https://github.com/{lock['upstream']}",
             f"- Release tag: `{lock['release_tag']}`", f"- Full commit: `{lock['commit_sha']}`",
             f"- Prepared against repository commit: `{base_sha}`",
             f"- Content SHA-256: `{lock['content_digest_sha256']}`",
             f"- Upstream diff: https://github.com/{lock['upstream']}/compare/{old['commit_sha']}...{lock['commit_sha']}",
             f"- Files: {len(changes['added'])} added, {len(changes['modified'])} modified, {len(changes['deleted'])} deleted.",
             f"- LICENSE changed: {'yes; review required' if changes['license_changed'] else 'no'}", "", "Subtree changes:"]
    for prefix in PATHS:
        counts = [sum(p.startswith(prefix + "/") for p in changes[k]) for k in ("added", "modified", "deleted")]
        lines.append(f"- `{prefix}`: {counts[0]} added, {counts[1]} modified, {counts[2]} deleted.")
    lines += ["", "Validation completed in the read-only job:",
              f"- {report['unit_tests']['count']} offline tests passed; Python/JavaScript syntax and static dependencies passed.",
              "- 12 detector cases and 10 synthetic runtime cases passed; report-only fixtures unchanged.",
              "- Write job rechecked bundle SHA-256, path allowlist, lock, dependencies and data patterns without running upstream code.",
              "", "Dependency review:", "- No unreviewed static dependency was accepted. Review all changed scripts for runtime behavior."]
    changed_scripts = sorted(p for k in ("added", "modified", "deleted") for p in changes[k] if "/scripts/" in p)
    lines.append(f"- Changed script files: {len(changed_scripts)} (listed below).")
    lines.append(f"- Reviewed optional asset/route warnings: {len(report['references']['warnings'])}; see read-only job logs.")
    lines += ["", "Changed files:", "```text"]
    for kind, symbol in (("added", "A"), ("modified", "M"), ("deleted", "D")):
        lines += [f"{symbol} {p}" for p in changes[kind]]
    lines += ["```", "", "Human review and merge are required. This workflow does not enable auto-merge.",
              "Approve the bot PR's pending CI workflows in GitHub before merging; read-only preparation already ran the checks.",
              "DSH discovery and model writing are not covered by these deterministic checks.", "",
              "Rollback: revert this PR's merge commit, validate the restored snapshot, then reinstall the previous accepted version.",
              "Private book files and provider configuration remain outside this repository."]
    return title, "\n".join(lines) + "\n"


def replace_snapshot(current: Path, candidate: Path, backup: Path) -> None:
    """Move complete subtrees, including deletions; restore originals on a failed move."""
    moved = []
    installed = []
    try:
        for relative in REPLACE_PATHS:
            original = current / relative
            saved = backup / relative
            saved.parent.mkdir(parents=True, exist_ok=True)
            original.rename(saved)
            moved.append(relative)
            (candidate / relative).rename(original)
            installed.append(relative)
    except OSError:
        for relative in reversed(installed):
            (current / relative).rename(candidate / relative)
        for relative in reversed(moved):
            (backup / relative).rename(current / relative)
        raise


def apply_bundle(current: Path, artifact: Path, expected_digest: str, expected_base_sha: str,
                 body_file: Path, output_file: Path) -> dict:
    verify_checkout(current, expected_base_sha)
    require(not body_file.exists() and not output_file.exists(), "metadata outputs must be new")
    cache = current / ".cache"
    cache.mkdir(exist_ok=True)
    require(plain_directory(cache), "checkout cache must not be a link/reparse point")
    with tempfile.TemporaryDirectory(prefix="apply-sync-", dir=cache) as temp:
        candidate, report = unpack_bundle(artifact, expected_digest, Path(temp) / "unpacked")
        changes = compare(current, candidate)
        if changes["changed"]:
            title, body = pr_metadata(current, candidate, report, changes, expected_base_sha)
            # Metadata is prepared before any repository snapshot paths are moved.
            body_file.write_bytes(body.encode("utf-8"))
            metadata = {"changed": True, "title": title, "base_sha": expected_base_sha,
                        "release_tag": json.loads((candidate / "upstream-lock.json").read_bytes())["release_tag"]}
            write_json(output_file, metadata)
            replace_snapshot(current, candidate, Path(temp) / "backup")
        else:
            metadata = {"changed": False}
            write_json(output_file, metadata)
    return metadata


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--expected-base-sha", required=True)
    parser.add_argument("--body-file", type=Path, required=True)
    parser.add_argument("--output-file", type=Path, required=True)
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()
    try:
        result = apply_bundle(args.current.resolve(), args.artifact, args.expected_sha256,
                              args.expected_base_sha, args.body_file, args.output_file)
        if args.github_output:
            with args.github_output.open("a", encoding="utf-8", newline="\n") as output:
                output.write(f"changed={str(result['changed']).lower()}\n")
                if result["changed"]:
                    output.write(f"title={result['title']}\n")
        print(json.dumps(result, indent=2))
        return 0
    except (SnapshotError, OSError, ValueError, TypeError, KeyError, tarfile.TarError, subprocess.CalledProcessError) as exc:
        print(f"ERROR: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
