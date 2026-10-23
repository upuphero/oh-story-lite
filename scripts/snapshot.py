"""Trusted, standard-library-only snapshot primitives. Never import upstream code."""

from __future__ import annotations

import hashlib
import json
import re
import stat
import unicodedata
from pathlib import Path, PurePosixPath

UPSTREAM = "zenstory-ai/oh-story-claudecode"
SKILLS = ("story-long-write", "story-deslop")
PATHS = tuple(f"skills/{name}" for name in SKILLS)
SHA_RE = re.compile(r"[0-9a-f]{40}")
HASH_RE = re.compile(r"[0-9a-f]{64}")
RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
            *(f"LPT{i}" for i in range(1, 10))}


class SnapshotError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SnapshotError(message)


def safe_path(raw: str) -> PurePosixPath:
    """Reject traversal and Windows aliases before any filesystem write."""
    require(isinstance(raw, str) and bool(raw), "empty path")
    require(not raw.startswith("/") and "\\" not in raw, f"unsafe path: {raw}")
    parts = raw.split("/")
    for part in parts:
        require(part not in {"", ".", ".."}, f"unsafe path: {raw}")
        require(not any(ord(c) < 32 or c in '<>:"|?*' for c in part), f"unsafe path: {raw}")
        require(not part.endswith((".", " ")), f"Windows alias: {raw}")
        require(part.split(".", 1)[0].upper() not in RESERVED, f"Windows reserved path: {raw}")
    return PurePosixPath(raw)


def portable_key(path: str) -> str:
    return unicodedata.normalize("NFC", path).casefold()


def allowed_file(path: str) -> bool:
    return path == "LICENSE" or any(path.startswith(p + "/") for p in PATHS)


def regular_file(path: Path) -> bool:
    info = path.lstat()
    return stat.S_ISREG(info.st_mode) and not getattr(info, "st_file_attributes", 0) & 0x400


def plain_directory(path: Path) -> bool:
    info = path.lstat()
    return stat.S_ISDIR(info.st_mode) and not getattr(info, "st_file_attributes", 0) & 0x400


def inventory(root: Path) -> dict[str, bytes]:
    """Read only the two allowed subtrees. Refuse symlinks and Windows junctions."""
    files: dict[str, bytes] = {}
    seen: set[str] = set()
    require((root / "skills").is_dir() and plain_directory(root / "skills"),
            "missing/linked skills directory")
    for prefix in PATHS:
        directory = root / prefix
        require(directory.is_dir(), f"missing Skill directory: {prefix}")
        pending = [directory]
        while pending:
            item = pending.pop()
            info = item.lstat()
            relative = item.relative_to(root).as_posix()
            safe_path(relative)
            require(not stat.S_ISLNK(info.st_mode)
                    and not getattr(info, "st_file_attributes", 0) & 0x400,
                    f"link/reparse point forbidden: {relative}")
            key = portable_key(relative)
            require(key not in seen, f"portable path collision: {relative}")
            seen.add(key)
            if stat.S_ISDIR(info.st_mode):
                pending.extend(item.iterdir())
            else:
                require(stat.S_ISREG(info.st_mode), f"special file: {relative}")
                files[relative] = item.read_bytes()
    return dict(sorted(files.items()))


def digest(files: dict[str, bytes]) -> str:
    h = hashlib.sha256()
    for path, data in sorted(files.items()):
        encoded = path.encode("utf-8")
        h.update(len(encoded).to_bytes(8, "big"))
        h.update(encoded)
        h.update(len(data).to_bytes(8, "big"))
        h.update(data)
    return h.hexdigest()


def file_manifest(files: dict[str, bytes]) -> dict:
    return {path: {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
            for path, data in sorted(files.items())}


def make_lock(root: Path, tag: str, sha: str) -> dict:
    require(SHA_RE.fullmatch(sha) is not None, "commit_sha must be a full lowercase 40-character SHA")
    require(re.fullmatch(r"v?\d+\.\d+\.\d+", tag) is not None, "expected a stable release tag")
    files = inventory(root)
    return {
        "schema_version": 1,
        "upstream": UPSTREAM,
        "release_tag": tag,
        "commit_sha": sha,
        "paths": list(PATHS),
        "digest_encoding": "sorted-path-utf8-u64be-length/raw-bytes-u64be-length-v1",
        "content_digest_sha256": digest(files),
        "skill_digests_sha256": {p: digest({k: v for k, v in files.items() if k.startswith(p + "/")})
                                 for p in PATHS},
        "license_sha256": hashlib.sha256((root / "LICENSE").read_bytes()).hexdigest(),
        "files": file_manifest(files),
    }


def write_json(path: Path, value: object) -> None:
    path.write_bytes((json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def compare(current: Path, candidate: Path) -> dict:
    new = inventory(candidate)
    if not (current / "skills").exists():
        require(not (current / "upstream-lock.json").exists(), "lock exists without skills")
        old = {}
    else:
        # Fail closed on a damaged local baseline; never silently repair provenance.
        from validate_layout import validate_layout
        validate_layout(current)
        old = inventory(current)
    license_changed = bool(old) and (current / "LICENSE").read_bytes() != (candidate / "LICENSE").read_bytes()
    result = {
        "added": sorted(new.keys() - old.keys()),
        "deleted": sorted(old.keys() - new.keys()),
        "modified": sorted(k for k in new.keys() & old.keys() if new[k] != old[k]),
        "license_changed": license_changed,
    }
    result["changed"] = bool(result["added"] or result["deleted"] or result["modified"])
    require(not (license_changed and not result["changed"]),
            "manual adaptation required: LICENSE changed without Skill changes")
    return result
