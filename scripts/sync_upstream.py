"""Prepare a new validated snapshot; never overwrite a checkout or execute upstream code."""

from __future__ import annotations

import argparse
import hashlib
import json
import tarfile
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

from snapshot import (PATHS, SHA_RE, UPSTREAM, SnapshotError, allowed_file, compare,
                      make_lock, portable_key, require, safe_path, write_json)

MAX_DOWNLOAD = 32 * 1024 * 1024
MAX_SELECTED = 32 * 1024 * 1024
MAX_FILE = 8 * 1024 * 1024
MAX_MEMBERS = 30000
MAX_UNPACKED = 128 * 1024 * 1024


def download(url: str, destination: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "oh-story-lite",
                                                 "Accept": "application/vnd.github+json"})
    # Public endpoints only: no token is needed or inherited by this downloader.
    with urllib.request.urlopen(request, timeout=60) as response, destination.open("wb") as output:
        size = 0
        while block := response.read(65536):
            size += len(block)
            require(size <= MAX_DOWNLOAD, "download exceeds size limit")
            output.write(block)


def resolve_release(cache: Path) -> tuple[str, str]:
    endpoint = f"https://api.github.com/repos/{UPSTREAM}"
    download(endpoint + "/releases/latest", cache / "release.json")
    release = json.loads((cache / "release.json").read_bytes())
    require(release.get("draft") is False and release.get("prerelease") is False,
            "expected the latest stable published release")
    tag = release["tag_name"]
    download(endpoint + "/commits/" + urllib.parse.quote(tag, safe=""), cache / "commit.json")
    sha = json.loads((cache / "commit.json").read_bytes())["sha"]
    require(isinstance(sha, str) and SHA_RE.fullmatch(sha) is not None, "invalid resolved commit SHA")
    return tag, sha


def stage_archive(archive: Path, destination: Path, sha: str) -> None:
    """Inspect all headers, then manually stream only regular allowlisted files."""
    require(SHA_RE.fullmatch(sha) is not None, "invalid full commit SHA")
    require(archive.stat().st_size <= MAX_DOWNLOAD, "archive exceeds size limit")
    expected_root = "oh-story-claudecode-" + sha
    selected = []
    seen: set[str] = set()
    total = 0
    unpacked = 0
    with tarfile.open(archive, "r:gz") as source:
        for number, member in enumerate(source, 1):
            require(number <= MAX_MEMBERS, "too many archive entries")
            unpacked += member.size
            require(0 <= member.size and unpacked <= MAX_UNPACKED, "archive exceeds uncompressed size limit")
            # tar directory headers may have one trailing slash.
            raw = member.name[:-1] if member.isdir() and member.name.endswith("/") else member.name
            path = safe_path(raw)
            require(path.parts[0] == expected_root, "archive root does not match resolved commit")
            key = portable_key(raw)
            require(key not in seen, f"duplicate/case-colliding archive entry: {raw}")
            seen.add(key)
            if len(path.parts) == 1:
                require(member.isdir(), "archive root must be a directory")
                continue
            relative = "/".join(path.parts[1:])
            if not allowed_file(relative):
                # Other upstream subtrees are data we deliberately do not distribute.
                if relative in ("skills", *PATHS):
                    require(member.isdir(), f"directory replaced by link/file: {relative}")
                continue
            require(member.isfile() or member.isdir(), f"link/special archive entry: {raw}")
            if member.isdir():
                require(relative != "LICENSE", "LICENSE must be a file")
                continue
            require(0 <= member.size <= MAX_FILE, f"oversized file: {relative}")
            total += member.size
            require(total <= MAX_SELECTED, "selected snapshot exceeds size limit")
            selected.append((member, relative))
        # Validate the whole header set before writing anything to the staging root.
        for member, relative in selected:
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            reader = source.extractfile(member)
            require(reader is not None, f"cannot read {relative}")
            with reader:
                data = reader.read(MAX_FILE + 1)
            require(len(data) == member.size, f"truncated archive file: {relative}")
            target.write_bytes(data)


def prepare(archive: Path, current: Path, tag: str, sha: str, output: Path | None) -> dict:
    from validate_layout import validate_layout
    from validate_references import validate_references
    from validate_all import validate_distribution_data

    if output is not None:
        require(not output.exists() and not output.is_symlink(), "output must be a new directory")
        require(output.parent.is_dir(), "output parent must already exist")
        require(not output.resolve().is_relative_to((current / "skills").resolve()),
                "output may not be inside current skills")
    # Same-volume staging enables an atomic directory rename. No existing tree is removed.
    with tempfile.TemporaryDirectory(prefix="oh-story-snapshot-", dir=output.parent if output else None) as temp:
        candidate = Path(temp) / "snapshot"
        candidate.mkdir()
        stage_archive(archive, candidate, sha)
        write_json(candidate / "upstream-lock.json", make_lock(candidate, tag, sha))
        layout = validate_layout(candidate)
        references = validate_references(candidate)
        validate_distribution_data(candidate)
        change = compare(current, candidate)
        result = {"release_tag": tag, "commit_sha": sha, **change, "layout": layout,
                  "references": references, "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest()}
        if change["changed"] and output is not None:
            # Rename fails rather than overwriting an existing destination on Windows.
            require(not output.exists(), "output appeared while preparing snapshot")
            candidate.rename(output)
            result["output"] = str(output)
        return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="report only; no candidate directory")
    mode.add_argument("--sync", action="store_true", help="write a new candidate directory on change")
    parser.add_argument("--current", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path)
    parser.add_argument("--archive", type=Path, help="offline archive; caller must verify GitHub provenance")
    parser.add_argument("--release-tag")
    parser.add_argument("--commit-sha")
    args = parser.parse_args()
    if args.sync != (args.output is not None):
        parser.error("--sync requires --output; --check does not accept --output")
    if bool(args.archive) != bool(args.release_tag and args.commit_sha) or (not args.archive and (args.release_tag or args.commit_sha)):
        parser.error("offline mode requires --archive, --release-tag and --commit-sha together")
    try:
        with tempfile.TemporaryDirectory(prefix="oh-story-download-") as temp:
            cache = Path(temp)
            if args.archive:
                archive, tag, sha = args.archive, args.release_tag, args.commit_sha
            else:
                tag, sha = resolve_release(cache)
                archive = cache / "upstream.tar.gz"
                download(f"https://codeload.github.com/{UPSTREAM}/tar.gz/{sha}", archive)
            result = prepare(archive, args.current.resolve(), tag, sha,
                             args.output.absolute() if args.output else None)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if not result["changed"]:
            print("No relevant changes")
        return 0
    except (SnapshotError, OSError, ValueError, TypeError, KeyError, tarfile.TarError) as exc:
        print(f"ERROR: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
