"""Offline Skill installer. All writes are bound to an explicitly named destination.

Uses complete directory moves, immutable pre-operation backups and a recovery
journal. Does not execute Skill code or install into an implicit user home.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import uuid

from snapshot import (HASH_RE, SHA_RE, SKILLS, SnapshotError, digest, file_manifest,
                      portable_key, require, safe_path, write_json)
from validate_all import validate_distribution_data
from validate_layout import validate_layout
from validate_references import validate_references

ROOT = Path(__file__).resolve().parents[1]
ENTRIES = (*(f"skills/{name}" for name in SKILLS), "active/install.json", "active/LICENSE")
ID_RE = re.compile(r"\d{8}T\d{6}Z-[0-9a-f]{12}")


def present(path: Path) -> bool:
    return os.path.lexists(path)


def same_destination(value: object, destination: Path) -> bool:
    return isinstance(value, str) and os.path.normcase(value) == os.path.normcase(str(destination))


def absolute(path: Path) -> Path:
    # Do not resolve() first: doing so would hide junctions and symlinks.
    result = Path(os.path.abspath(path))
    require(not str(result).startswith("\\\\"), "UNC/device destinations are not supported")
    return result


def check_plain(path: Path, directory: bool | None = None) -> None:
    info = path.lstat()
    require(not stat.S_ISLNK(info.st_mode) and not getattr(info, "st_file_attributes", 0) & 0x400,
            f"link/reparse point forbidden: {path}")
    if directory is not None:
        require(stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode),
                f"unexpected file type: {path}")
    else:
        require(stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode), f"special file forbidden: {path}")


def check_ancestors(path: Path) -> None:
    for item in reversed((path, *path.parents)):
        if present(item):
            check_plain(item, True)


def destination_paths(destination: Path) -> tuple[Path, Path]:
    destination = absolute(destination)
    require(destination != Path(destination.anchor), "filesystem root cannot be a Skills destination")
    check_ancestors(destination)
    key = hashlib.sha256(os.path.normcase(str(destination)).encode("utf-8")).hexdigest()[:16]
    state = destination.parent / ".oh-story-lite" / key
    require(not destination.is_relative_to(state.parent), "destination cannot be inside installer state")
    check_ancestors(state)
    return destination, state


def live_entries(destination: Path, state: Path) -> dict[str, Path]:
    return {**{f"skills/{name}": destination / name for name in SKILLS},
            "active/install.json": state / "install.json", "active/LICENSE": state / "LICENSE"}


def scan(entries: dict[str, Path]) -> tuple[dict, dict[str, bytes]]:
    files = {}
    directories = []
    roots = []
    seen = set()
    for name, path in entries.items():
        check_ancestors(path.parent)
        if not present(path):
            continue
        roots.append(name)
        check_plain(path, name.startswith("skills/"))
        pending = [(name, path)]
        while pending:
            relative, item = pending.pop()
            safe_path(relative)
            check_plain(item)
            key = portable_key(relative)
            require(key not in seen, f"portable path collision: {relative}")
            seen.add(key)
            if item.is_dir():
                directories.append(relative)
                pending.extend((relative + "/" + child.name, child) for child in item.iterdir())
            else:
                files[relative] = item.read_bytes()
    summary = {"roots": sorted(roots), "directories": sorted(directories),
               "files": file_manifest(files), "content_digest_sha256": digest(files)}
    return summary, files


def container_entries(root: Path) -> dict[str, Path]:
    check_ancestors(root)
    require({p.name for p in root.iterdir()} <= {"skills", "active"}, "extra snapshot container path")
    for name, allowed in (("skills", set(SKILLS)), ("active", {"install.json", "LICENSE"})):
        path = root / name
        if present(path):
            check_plain(path, True)
            require({p.name for p in path.iterdir()} <= allowed, f"extra {name} snapshot path")
    return {name: root / name for name in ENTRIES}


def capture(entries: dict[str, Path], output: Path) -> dict:
    before, files = scan(entries)
    require(not present(output), "snapshot output must be new")
    output.mkdir(parents=True)
    for relative in before["directories"]:
        (output / relative).mkdir(parents=True, exist_ok=True)
    for relative, data in files.items():
        path = output / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    require(scan(container_entries(output))[0] == before, "copied snapshot does not match source")
    require(scan(entries)[0] == before, "source changed while making backup")
    return before


def read_receipt(entries: dict[str, Path], destination: Path) -> dict | None:
    receipt_path = entries["active/install.json"]
    license_path = entries["active/LICENSE"]
    if not present(receipt_path):
        require(not present(license_path), "installer LICENSE exists without a receipt")
        return None
    check_plain(receipt_path, False)
    receipt = json.loads(receipt_path.read_bytes())
    require(isinstance(receipt, dict) and receipt.get("schema_version") == 1
            and same_destination(receipt.get("destination"), destination), "invalid or foreign installation receipt")
    lock = receipt.get("upstream_lock", {})
    require(SHA_RE.fullmatch(lock.get("commit_sha", "")) is not None
            and HASH_RE.fullmatch(lock.get("content_digest_sha256", "")) is not None
            and isinstance(lock.get("files"), dict), "invalid installed version metadata")
    check_plain(license_path, False)
    require(hashlib.sha256(license_path.read_bytes()).hexdigest() == lock.get("license_sha256"),
            "installer LICENSE does not match installed version metadata")
    return receipt


def new_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:12]


def check_id(identifier: str) -> None:
    require(isinstance(identifier, str) and ID_RE.fullmatch(identifier) is not None, "invalid backup/transaction ID")


@contextmanager
def exclusive(state: Path):
    check_ancestors(state)
    state.mkdir(parents=True, exist_ok=True)
    lock_path = state / "installer.lock"
    if present(lock_path):
        check_plain(lock_path, False)
    with lock_path.open("a+b") as handle:
        if lock_path.stat().st_size == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise SnapshotError("another installer operation is running") from exc
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def atomic_json(path: Path, value: dict) -> None:
    temporary = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex)
    write_json(temporary, value)
    with temporary.open("ab") as handle:
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def remove_private_tree(path: Path, state: Path) -> None:
    # Recursive removal is restricted to installer-owned transaction staging.
    path = absolute(path)
    require(path.is_relative_to(state / "transactions") and path != state / "transactions",
            "refusing cleanup outside transaction staging")
    check_ancestors(path)
    for directory, folders, files in os.walk(path, followlinks=False):
        for name in folders + files:
            check_plain(Path(directory) / name)
    shutil.rmtree(path)


def load_backup(state: Path, destination: Path, identifier: str) -> tuple[Path, dict]:
    check_id(identifier)
    backup = state / "backups" / identifier
    check_ancestors(backup)
    require({p.name for p in backup.iterdir()} == {"backup.json", "payload"}, "invalid backup container")
    check_plain(backup / "backup.json", False)
    manifest = json.loads((backup / "backup.json").read_bytes())
    require(isinstance(manifest, dict) and manifest.get("schema_version") == 1
            and manifest.get("id") == identifier and same_destination(manifest.get("destination"), destination),
            "backup belongs to another destination or has invalid metadata")
    entries = container_entries(backup / "payload")
    require(scan(entries)[0] == manifest.get("snapshot"), "backup integrity check failed")
    read_receipt(entries, destination)
    return backup / "payload", manifest


def save_backup(destination: Path, state: Path, operation: str, identifier: str) -> dict:
    entries = live_entries(destination, state)
    receipt = read_receipt(entries, destination)
    backup = state / "backups" / identifier
    check_ancestors(backup.parent)
    building = state / "transactions" / identifier / "backup-building"
    building.mkdir()
    summary = capture(entries, building / "payload")
    manifest = {"schema_version": 1, "id": identifier, "destination": str(destination),
                "created_utc": datetime.now(timezone.utc).isoformat(), "operation": operation,
                "before_version": receipt["upstream_lock"]["release_tag"] if receipt else None,
                "snapshot": summary}
    atomic_json(building / "backup.json", manifest)
    backup.parent.mkdir(parents=True, exist_ok=True)
    building.rename(backup)
    load_backup(state, destination, identifier)
    return manifest


def journal_data(state: Path, destination: Path) -> dict:
    check_plain(state / "pending.json", False)
    journal = json.loads((state / "pending.json").read_bytes())
    require(isinstance(journal, dict) and journal.get("schema_version") == 1
            and same_destination(journal.get("destination"), destination)
            and journal.get("phase") in {"prepared", "committed"}, "invalid recovery journal")
    check_id(journal.get("id", ""))
    return journal


def restore_pending(destination: Path, state: Path) -> dict:
    journal = journal_data(state, destination)
    identifier = journal["id"]
    _, manifest = load_backup(state, destination, identifier)
    transaction = state / "transactions" / identifier
    check_ancestors(transaction)
    if not present(transaction):
        require(journal["phase"] == "committed" or scan(live_entries(destination, state))[0] == manifest["snapshot"],
                "transaction staging is missing and previous state is not restored")
        (state / "pending.json").unlink()
        return {"changed": True, "action": "Recover", "recovered_transaction": identifier,
                "outcome": "finished_recovery_cleanup"}
    if journal["phase"] == "prepared":
        # Keep every displaced original until recovery has been verified. Copying
        # originals makes recovery retryable even if recovery itself is interrupted.
        live = live_entries(destination, state)
        old_roots = set(manifest["snapshot"]["roots"])
        for name in ENTRIES:
            saved = transaction / "displaced" / name
            desired = transaction / "desired" / name
            target = live[name]
            if present(saved) or (name not in old_roots and not present(desired)):
                if present(target):
                    check_plain(target, name.startswith("skills/"))
                    # Retain partial new data until the whole recovery succeeds.
                    quarantined = transaction / "recovery" / uuid.uuid4().hex / name
                    quarantined.parent.mkdir(parents=True)
                    target.rename(quarantined)
                if present(saved):
                    scan({name: saved})
                    check_plain(saved, name.startswith("skills/"))
                    if saved.is_dir():
                        shutil.copytree(saved, target)
                    else:
                        shutil.copyfile(saved, target)
        require(scan(live)[0] == manifest["snapshot"],
                "recovery incomplete; preserve state and retry Recover after releasing file locks")
    remove_private_tree(transaction, state)
    (state / "pending.json").unlink()
    return {"changed": True, "action": "Recover", "recovered_transaction": identifier,
            "outcome": "restored_previous_state" if journal["phase"] == "prepared" else "finished_committed_cleanup"}


def transact(destination: Path, state: Path, desired_root: Path, operation: str, identifier: str) -> dict:
    desired, _ = scan(container_entries(desired_root))
    live = live_entries(destination, state)
    if scan(live)[0] == desired:
        return {"changed": False, "action": operation, "backup_id": None}
    before = save_backup(destination, state, operation, identifier)
    transaction = desired_root.parent
    journal = {"schema_version": 1, "id": identifier, "destination": str(destination), "phase": "prepared"}
    atomic_json(state / "pending.json", journal)
    try:
        for name in ENTRIES:
            target = live[name]
            if present(target):
                saved = transaction / "displaced" / name
                saved.parent.mkdir(parents=True, exist_ok=True)
                target.rename(saved)
            staged = desired_root / name
            if present(staged):
                target.parent.mkdir(parents=True, exist_ok=True)
                staged.rename(target)
        require(scan(live)[0] == desired, "installed bytes do not match staged snapshot")
        journal["phase"] = "committed"
        atomic_json(state / "pending.json", journal)
    except (OSError, SnapshotError):
        # A failed recovery leaves the journal and immutable backup intact.
        restore_pending(destination, state)
        raise
    remove_private_tree(transaction, state)
    (state / "pending.json").unlink()
    return {"changed": True, "action": operation, "backup_id": before["id"]}


def prepare_source(source: Path, destination: Path) -> tuple[dict, bytes]:
    source = absolute(source)
    check_ancestors(source)
    source_skills = source / "skills"
    require(not destination.is_relative_to(source_skills) and not source_skills.is_relative_to(destination),
            "destination overlaps source distribution")
    validate_layout(source)
    validate_references(source)
    validate_distribution_data(source)
    lock = json.loads((source / "upstream-lock.json").read_bytes())
    return {"schema_version": 1, "destination": str(destination), "upstream_lock": lock}, (source / "LICENSE").read_bytes()


def status(destination: Path, state: Path) -> dict:
    if present(state / "pending.json"):
        journal = journal_data(state, destination)
        return {"destination": str(destination), "state_directory": str(state), "recovery_required": True,
                "transaction": journal["id"], "phase": journal["phase"], "release_tag": None}
    entries = live_entries(destination, state)
    summary, _ = scan(entries)
    receipt = read_receipt(entries, destination)
    actual = {p: data for p, data in summary["files"].items() if p.startswith("skills/")}
    return {"destination": str(destination), "state_directory": str(state), "managed": receipt is not None,
            "release_tag": receipt["upstream_lock"]["release_tag"] if receipt else None,
            "commit_sha": receipt["upstream_lock"]["commit_sha"] if receipt else None,
            "present_skills": [s for s in SKILLS if f"skills/{s}" in summary["roots"]],
            "locally_modified": actual != receipt["upstream_lock"]["files"] if receipt else None,
            "recovery_required": present(state / "pending.json")}


def manage(action: str, destination: Path, source: Path = ROOT, backup_id: str | None = None) -> dict:
    destination, state = destination_paths(destination)
    if action == "Status":
        return status(destination, state)
    if action == "Backups":
        result = []
        directory = state / "backups"
        check_ancestors(directory)
        if directory.exists():
            for backup in sorted(directory.iterdir(), reverse=True):
                _, manifest = load_backup(state, destination, backup.name)
                result.append({k: manifest[k] for k in ("id", "created_utc", "operation", "before_version")})
        return {"destination": str(destination), "backups": result}
    require(action in {"Install", "Upgrade", "Rollback", "Recover"}, "unknown installer action")
    receipt = license_data = None
    if action in {"Install", "Upgrade"}:
        receipt, license_data = prepare_source(source, destination)
    if action == "Rollback":
        require(backup_id is not None, "Rollback requires an explicit backup ID")
        check_id(backup_id)
        require(state.is_dir(), "no installer state for this destination")
    if action == "Recover":
        require(present(state / "pending.json"), "no pending transaction to recover")
    with exclusive(state):
        if action == "Recover":
            return {**restore_pending(destination, state), **status(destination, state)}
        require(not present(state / "pending.json"), "pending transaction; run Recover before another change")
        old_receipt = read_receipt(live_entries(destination, state), destination)
        if receipt is not None and old_receipt is not None:
            # Windows spellings of the same path should not cause metadata-only upgrades.
            receipt["destination"] = old_receipt["destination"]
        if action == "Upgrade":
            require(old_receipt is not None, "Upgrade requires a managed install; use Install to back up/adopt existing directories")
        identifier = new_id()
        transaction = state / "transactions" / identifier
        check_ancestors(transaction.parent)
        try:
            if action == "Rollback":
                payload, _ = load_backup(state, destination, backup_id)
                capture(container_entries(payload), transaction / "desired")
            else:
                staged = transaction / "desired"
                capture({f"skills/{s}": absolute(source) / "skills" / s for s in SKILLS}, staged)
                (staged / "active").mkdir()
                write_json(staged / "active/install.json", receipt)
                (staged / "active/LICENSE").write_bytes(license_data)
                # Verify staged bytes against the validated source manifest.
                actual, _ = scan(container_entries(staged))
                require({p: data for p, data in actual["files"].items() if p.startswith("skills/")}
                        == receipt["upstream_lock"]["files"], "source changed during staging")
            result = transact(destination, state, transaction / "desired", action, identifier)
        finally:
            if not present(state / "pending.json") and transaction.exists():
                remove_private_tree(transaction, state)
        return {**result, "restored_from": backup_id if action == "Rollback" else None, **status(destination, state)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--action", choices=("Install", "Upgrade", "Rollback", "Backups", "Status", "Recover"), default="Install")
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--source", type=Path, default=ROOT)
    parser.add_argument("--backup-id")
    args = parser.parse_args()
    try:
        print(json.dumps(manage(args.action, args.destination, args.source, args.backup_id), ensure_ascii=False, indent=2))
        return 0
    except (SnapshotError, OSError, ValueError, TypeError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
