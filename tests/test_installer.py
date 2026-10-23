"""Installer lifecycle tests; every destination is under the ignored workspace cache."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from manage_install import (destination_paths, exclusive, live_entries, load_backup,
                            manage, scan)
from snapshot import SnapshotError, SKILLS, make_lock, write_json


class InstallerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (ROOT / ".cache").mkdir(exist_ok=True)
        cls.fixtures = tempfile.TemporaryDirectory(prefix="installer-sources-", dir=ROOT / ".cache")
        cls.old = Path(cls.fixtures.name) / "old snapshot"
        shutil.copytree(ROOT / "skills", cls.old / "skills")
        shutil.copyfile(ROOT / "LICENSE", cls.old / "LICENSE")
        (cls.old / "skills/story-deslop/references/obsolete.md").write_bytes(b"Synthetic old asset.\n")
        write_json(cls.old / "upstream-lock.json", make_lock(cls.old, "v0.9.0", "a" * 40))
        cls.new = Path(cls.fixtures.name) / "new snapshot"
        shutil.copytree(cls.old, cls.new)
        (cls.new / "skills/story-deslop/references/obsolete.md").unlink()
        (cls.new / "skills/story-deslop/references/new.md").write_bytes(b"Synthetic new asset.\n")
        path = cls.new / "skills/story-deslop/references/expression.md"
        path.write_bytes(path.read_bytes() + b"\nSynthetic fixture change.\n")
        write_json(cls.new / "upstream-lock.json", make_lock(cls.new, "v0.9.1", "b" * 40))

    @classmethod
    def tearDownClass(cls):
        cls.fixtures.cleanup()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="test-installer-", dir=ROOT / ".cache")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        # Exercise literal spaces and Unicode through Python and PowerShell.
        self.destination = self.directory / "隔离 home" / ".agents" / "skills"
        self.destination.mkdir(parents=True)
        other = self.destination / "unrelated-skill"
        other.mkdir()
        self.sentinel = other / "SKILL.md"
        self.sentinel.write_bytes(b"Do not touch unrelated Skills.\n")
        self.destination, self.state = destination_paths(self.destination)

    def run_action(self, action, source=None, backup_id=None):
        result = manage(action, self.destination, source or self.old, backup_id)
        self.assertEqual(self.sentinel.read_bytes(), b"Do not touch unrelated Skills.\n")
        return result

    def summary(self):
        return scan(live_entries(self.destination, self.state))[0]

    def test_install_keeps_backups_outside_skill_discovery(self):
        result = self.run_action("Install")
        self.assertTrue(result["changed"])
        self.assertFalse(result["locally_modified"])
        self.assertFalse(self.state.is_relative_to(self.destination))
        self.assertEqual({p.name for p in self.destination.iterdir()}, {*SKILLS, "unrelated-skill"})
        payload, before = load_backup(self.state, self.destination, result["backup_id"])
        self.assertEqual(before["snapshot"]["roots"], [])
        self.assertEqual((self.state / "LICENSE").read_bytes(), (ROOT / "LICENSE").read_bytes())

    def test_readonly_actions_do_not_create_state_or_destination(self):
        destination = self.directory / "not created" / "skills"
        result = manage("Status", destination)
        self.assertFalse(result["managed"])
        self.assertEqual(manage("Backups", destination)["backups"], [])
        self.assertFalse(destination.parent.exists())

    def test_upgrade_removes_deleted_assets_and_preserves_backup(self):
        self.run_action("Install")
        result = self.run_action("Upgrade", self.new)
        self.assertEqual(result["release_tag"], "v0.9.1")
        self.assertFalse((self.destination / "story-deslop/references/obsolete.md").exists())
        self.assertTrue((self.destination / "story-deslop/references/new.md").exists())
        payload, before = load_backup(self.state, self.destination, result["backup_id"])
        self.assertEqual(before["before_version"], "v0.9.0")
        self.assertTrue((payload / "skills/story-deslop/references/obsolete.md").exists())

    def test_rollback_restores_exact_previous_files_receipt_and_version(self):
        self.run_action("Install")
        before = self.summary()
        upgraded = self.run_action("Upgrade", self.new)
        result = self.run_action("Rollback", backup_id=upgraded["backup_id"])
        self.assertEqual(self.summary(), before)
        self.assertEqual(result["release_tag"], "v0.9.0")
        self.assertEqual(result["restored_from"], upgraded["backup_id"])
        self.assertNotEqual(result["backup_id"], upgraded["backup_id"])

    def test_rollback_is_itself_undoable(self):
        self.run_action("Install")
        upgraded = self.run_action("Upgrade", self.new)
        new_summary = self.summary()
        rollback = self.run_action("Rollback", backup_id=upgraded["backup_id"])
        result = self.run_action("Rollback", backup_id=rollback["backup_id"])
        self.assertEqual(result["release_tag"], "v0.9.1")
        self.assertEqual(self.summary(), new_summary)

    def test_rollback_first_install_restores_absence_without_deleting_other_skills(self):
        installed = self.run_action("Install")
        result = self.run_action("Rollback", backup_id=installed["backup_id"])
        self.assertFalse(result["managed"])
        self.assertEqual(result["present_skills"], [])
        self.assertEqual(list(self.destination.iterdir()), [self.sentinel.parent])

    def test_install_adopts_legacy_partial_directories_and_restores_empty_dirs_binary_files(self):
        old = self.destination / "story-long-write"
        (old / "empty").mkdir(parents=True)
        (old / "local.bin").write_bytes(b"\x00\xfflocal legacy data\x01")
        before = self.summary()
        result = self.run_action("Install")
        self.run_action("Rollback", backup_id=result["backup_id"])
        self.assertEqual(self.summary(), before)
        self.assertFalse((self.destination / "story-deslop").exists())

    def test_same_snapshot_is_noop_without_new_backup_or_receipt_rewrite(self):
        self.run_action("Install")
        before = self.run_action("Backups")
        receipt = self.state / "install.json"
        modified = receipt.stat().st_mtime_ns
        result = self.run_action("Upgrade")
        self.assertFalse(result["changed"])
        self.assertEqual(before, self.run_action("Backups"))
        self.assertEqual(modified, receipt.stat().st_mtime_ns)

    def test_local_edits_are_backed_up_and_restored(self):
        self.run_action("Install")
        path = self.destination / "story-deslop/references/expression.md"
        path.write_bytes(b"Local edits must survive in backup.\r\n")
        self.assertTrue(self.run_action("Status")["locally_modified"])
        before = self.summary()
        result = self.run_action("Upgrade", self.new)
        self.assertFalse(result["locally_modified"])
        restored = self.run_action("Rollback", backup_id=result["backup_id"])
        self.assertTrue(restored["locally_modified"])
        self.assertEqual(self.summary(), before)

    def test_upgrade_requires_an_existing_managed_install(self):
        with self.assertRaisesRegex(SnapshotError, "managed install"):
            self.run_action("Upgrade")
        self.assertFalse((self.destination / SKILLS[0]).exists())

    def test_invalid_source_fails_before_state_or_skill_writes(self):
        source = self.directory / "invalid source"
        shutil.copytree(self.old, source)
        (source / "skills/story-deslop/SKILL.md").write_bytes(b"Invalid source.\n")
        with self.assertRaises(SnapshotError):
            self.run_action("Install", source)
        self.assertFalse(self.state.exists())
        self.assertEqual(list(self.destination.iterdir()), [self.sentinel.parent])

    def test_destination_cannot_overlap_source_or_be_filesystem_root(self):
        for destination in (self.old, self.old / "skills", self.old / "skills/story-deslop", Path(self.destination.anchor)):
            with self.subTest(destination=destination), self.assertRaises(SnapshotError):
                manage("Install", destination, self.old)

    def test_rollback_requires_valid_explicit_id(self):
        self.run_action("Install")
        before = self.summary()
        for identifier in (None, "../escape", "latest", "C:\\outside"):
            with self.subTest(identifier=identifier), self.assertRaises(SnapshotError):
                self.run_action("Rollback", backup_id=identifier)
        self.assertEqual(self.summary(), before)

    def test_tampered_backup_is_rejected_before_installed_files_change(self):
        self.run_action("Install")
        upgraded = self.run_action("Upgrade", self.new)
        payload, _ = load_backup(self.state, self.destination, upgraded["backup_id"])
        (payload / "skills/story-deslop/SKILL.md").write_bytes(b"tampered\n")
        before = self.summary()
        with self.assertRaisesRegex(SnapshotError, "integrity"):
            self.run_action("Rollback", backup_id=upgraded["backup_id"])
        self.assertEqual(self.summary(), before)

    def test_foreign_backup_cannot_be_restored_to_another_destination(self):
        self.run_action("Install")
        upgraded = self.run_action("Upgrade", self.new)
        other, state = destination_paths(self.directory / "other home" / "skills")
        backup = state / "backups" / upgraded["backup_id"]
        shutil.copytree(self.state / "backups" / upgraded["backup_id"], backup)
        with self.assertRaisesRegex(SnapshotError, "another destination"):
            manage("Rollback", other, backup_id=upgraded["backup_id"])
        self.assertFalse(other.exists())

    def test_extra_backup_paths_are_rejected(self):
        self.run_action("Install")
        result = self.run_action("Upgrade", self.new)
        payload, _ = load_backup(self.state, self.destination, result["backup_id"])
        (payload / "skills/third").mkdir()
        with self.assertRaisesRegex(SnapshotError, "extra skills"):
            self.run_action("Rollback", backup_id=result["backup_id"])

    def test_move_failure_automatically_restores_original_state(self):
        self.run_action("Install")
        before = self.summary()
        rename = Path.rename
        def fail_second_skill(path, target):
            if path.name == "story-deslop" and "desired" in path.parts:
                raise OSError("synthetic replacement failure")
            return rename(path, target)
        with patch.object(Path, "rename", fail_second_skill):
            with self.assertRaisesRegex(OSError, "synthetic replacement failure"):
                self.run_action("Upgrade", self.new)
        self.assertEqual(self.summary(), before)
        self.assertFalse((self.state / "pending.json").exists())

    def test_interrupted_upgrade_requires_recover_and_restores_exact_previous_state(self):
        self.run_action("Install")
        before = self.summary()
        rename = Path.rename
        def interrupt_second_skill(path, target):
            if path.name == "story-deslop" and "desired" in path.parts:
                raise KeyboardInterrupt("synthetic process interruption")
            return rename(path, target)
        with patch.object(Path, "rename", interrupt_second_skill), self.assertRaises(KeyboardInterrupt):
            self.run_action("Upgrade", self.new)
        self.assertTrue((self.state / "pending.json").exists())
        self.assertTrue(self.run_action("Status")["recovery_required"])
        with self.assertRaisesRegex(SnapshotError, "run Recover"):
            self.run_action("Upgrade", self.new)
        result = self.run_action("Recover")
        self.assertEqual(result["outcome"], "restored_previous_state")
        self.assertEqual(self.summary(), before)
        self.assertFalse(result["recovery_required"])

    def test_recovery_failure_keeps_backup_and_journal_for_retry(self):
        self.run_action("Install")
        before = self.summary()
        rename = Path.rename
        def fail_replace_and_recovery(path, target):
            if ((path.name == "story-deslop" and "desired" in path.parts)
                    or (path == self.destination / "story-long-write" and "recovery" in target.parts)):
                raise OSError("synthetic busy file")
            return rename(path, target)
        with patch.object(Path, "rename", fail_replace_and_recovery), self.assertRaises(OSError):
            self.run_action("Upgrade", self.new)
        self.assertTrue((self.state / "pending.json").exists())
        self.run_action("Recover")
        self.assertEqual(self.summary(), before)

    def test_committed_cleanup_failure_recovers_without_undoing_successful_upgrade(self):
        self.run_action("Install")
        with patch("manage_install.remove_private_tree", side_effect=OSError("synthetic cleanup failure")):
            with self.assertRaises(OSError):
                self.run_action("Upgrade", self.new)
        result = self.run_action("Recover")
        self.assertEqual(result["release_tag"], "v0.9.1")
        self.assertEqual(result["outcome"], "finished_committed_cleanup")

    def test_backup_write_failure_leaves_current_install_unchanged(self):
        self.run_action("Install")
        before = self.summary()
        from manage_install import atomic_json
        def fail_backup(path, value):
            if path.name == "backup.json":
                raise OSError("synthetic full disk")
            return atomic_json(path, value)
        with patch("manage_install.atomic_json", side_effect=fail_backup), self.assertRaises(OSError):
            self.run_action("Upgrade", self.new)
        self.assertEqual(self.summary(), before)
        self.assertFalse((self.state / "pending.json").exists())
        # Incomplete backups stay private in staging and are not listed as valid backups.
        self.assertEqual(len(self.run_action("Backups")["backups"]), 1)

    def test_concurrent_installer_is_rejected(self):
        with exclusive(self.state), self.assertRaisesRegex(SnapshotError, "another installer"):
            self.run_action("Install")

    def test_installer_does_not_execute_skill_code(self):
        source = self.directory / "do not execute"
        shutil.copytree(self.old, source)
        path = source / "skills/story-deslop/scripts/check-degeneration.js"
        path.write_bytes(path.read_bytes() + b'\nthrow new Error("not executed by installer");\n')
        write_json(source / "upstream-lock.json", make_lock(source, "v0.9.0", "a" * 40))
        with patch("subprocess.run", side_effect=AssertionError("installer must not execute candidate code")):
            self.assertTrue(self.run_action("Install", source)["changed"])

    def test_target_symlink_or_junction_is_rejected(self):
        outside = self.directory / "other directory"
        outside.mkdir()
        (outside / "keep.md").write_bytes(b"keep\n")
        link = self.destination / "story-long-write"
        if os.name == "nt":
            command = ["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(outside)]
            result = subprocess.run(command, capture_output=True)
            if result.returncode:
                self.skipTest("junction creation unavailable")
            self.addCleanup(os.rmdir, link)
        else:
            link.symlink_to(outside, target_is_directory=True)
            self.addCleanup(link.unlink)
        with self.assertRaisesRegex(SnapshotError, "link/reparse"):
            self.run_action("Install")
        self.assertEqual((outside / "keep.md").read_bytes(), b"keep\n")

    def test_destination_ancestor_junction_is_rejected(self):
        outside = self.directory / "redirect directory"
        outside.mkdir()
        link = self.directory / "redirected home"
        if os.name == "nt":
            result = subprocess.run(["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(outside)], capture_output=True)
            if result.returncode:
                self.skipTest("junction creation unavailable")
            self.addCleanup(os.rmdir, link)
        else:
            link.symlink_to(outside, target_is_directory=True)
            self.addCleanup(link.unlink)
        with self.assertRaisesRegex(SnapshotError, "link/reparse"):
            manage("Install", link / "skills", self.old)
        self.assertEqual(list(outside.iterdir()), [])

    def test_powershell_entrypoint_lifecycle_in_isolated_directories(self):
        shells = [p for name in ("pwsh", "powershell") if (p := shutil.which(name))]
        if not shells:
            if os.name == "nt":
                self.fail("Windows must provide PowerShell for installer validation")
            self.skipTest("PowerShell wrapper is Windows-specific; Python lifecycle remains tested")
        for index, shell in enumerate(shells):
            with self.subTest(shell=shell):
                destination = self.directory / f"PowerShell 隔离 {index}" / ".agents" / "skills"
                def invoke(action, source=None, backup_id=None):
                    command = [shell, "-NoProfile", "-NonInteractive", "-File", str(ROOT / "install.ps1"),
                               "-Action", action, "-Destination", str(destination),
                               "-Source", str(source or self.old), "-PythonExecutable", sys.executable]
                    if backup_id:
                        command += ["-BackupId", backup_id]
                    result = subprocess.run(command, capture_output=True, encoding="utf-8", timeout=60)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    return json.loads(result.stdout)
                self.assertEqual(invoke("Install")["release_tag"], "v0.9.0")
                upgraded = invoke("Upgrade", self.new)
                self.assertEqual(upgraded["release_tag"], "v0.9.1")
                self.assertEqual(invoke("Rollback", backup_id=upgraded["backup_id"])["release_tag"], "v0.9.0")
                self.assertFalse(invoke("Status")["locally_modified"])

    def test_powershell_requires_explicit_destination(self):
        shell = shutil.which("pwsh") or shutil.which("powershell")
        if not shell:
            self.skipTest("PowerShell not installed")
        result = subprocess.run([shell, "-NoProfile", "-NonInteractive", "-File", str(ROOT / "install.ps1"),
                                 "-Action", "Install"], capture_output=True, timeout=30)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.state.exists())

    @unittest.skipUnless(os.name == "nt", "Windows case-insensitive path semantics")
    def test_windows_path_case_does_not_create_a_spurious_upgrade(self):
        self.run_action("Install")
        result = manage("Upgrade", Path(str(self.destination).swapcase()), self.old)
        self.assertFalse(result["changed"])


if __name__ == "__main__":
    unittest.main()
