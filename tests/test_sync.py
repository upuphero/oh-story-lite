"""Offline integration tests using synthetic archives of the pinned local snapshot."""

from __future__ import annotations

import io
import json
import shutil
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from snapshot import (SnapshotError, digest, inventory, make_lock,
                      safe_path, write_json)
from sync_upstream import MAX_FILE, prepare, resolve_release, stage_archive
from validate_all import validate_distribution_data
from validate_layout import validate_layout
from validate_references import validate_references

SHA = "a" * 40
ARCHIVE_ROOT = "oh-story-claudecode-" + SHA


class SyncTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = inventory(ROOT)
        cls.license = (ROOT / "LICENSE").read_bytes()
        (ROOT / ".cache").mkdir(exist_ok=True)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="test-sync-", dir=ROOT / ".cache")
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.current = self.directory / "current"
        shutil.copytree(ROOT / "skills", self.current / "skills")
        shutil.copyfile(ROOT / "LICENSE", self.current / "LICENSE")
        self.relock()
        self.archive = self.directory / "source.tar.gz"
        self.output = self.directory / "candidate"

    def relock(self):
        write_json(self.current / "upstream-lock.json", make_lock(self.current, "v0.9.0", SHA))

    def write_archive(self, changes=None, removed=(), extras=(), license_data=None):
        files = {**self.original, "LICENSE": self.license if license_data is None else license_data}
        for key in removed:
            files.pop(key, None)
        files.update(changes or {})
        with tarfile.open(self.archive, "w:gz") as archive:
            for name, data in files.items():
                entry = tarfile.TarInfo(ARCHIVE_ROOT + "/" + name)
                entry.size = len(data)
                archive.addfile(entry, io.BytesIO(data))
            for entry, data in extras:
                archive.addfile(entry, io.BytesIO(data) if data is not None else None)

    def prepare(self, tag="v0.9.1"):
        return prepare(self.archive, self.current, tag, SHA, self.output)

    def test_noop_keeps_lock_and_emits_no_directory(self):
        self.write_archive()
        before = (self.current / "upstream-lock.json").read_bytes()
        result = self.prepare()
        self.assertFalse(result["changed"])
        self.assertFalse(self.output.exists())
        self.assertEqual(before, (self.current / "upstream-lock.json").read_bytes())

    def test_unrelated_upstream_changes_are_noop(self):
        self.write_archive({"skills/story-other/SKILL.md": b"other", "README.md": b"new upstream readme",
                            ".github/workflows/injection.yml": b"bad", "scripts/local.py": b"bad"})
        self.assertFalse(self.prepare()["changed"])

    def test_update_emits_only_allowed_snapshot(self):
        path = "skills/story-deslop/references/expression.md"
        self.write_archive({path: self.original[path] + b"\nUpdated.\n", "prompts/custom.md": b"not allowed"})
        result = self.prepare()
        self.assertEqual(result["modified"], [path])
        self.assertEqual({p.name for p in self.output.iterdir()}, {"skills", "LICENSE", "upstream-lock.json"})
        self.assertEqual((self.current / path).read_bytes(), self.original[path])
        self.assertEqual(validate_layout(self.output)["files"], 102)

    def test_deleted_file_is_not_carried_forward(self):
        obsolete = self.current / "skills/story-deslop/references/obsolete.md"
        obsolete.write_bytes(b"obsolete\n")
        self.relock()
        self.write_archive()
        result = self.prepare()
        self.assertEqual(result["deleted"], ["skills/story-deslop/references/obsolete.md"])
        self.assertFalse((self.output / "skills/story-deslop/references/obsolete.md").exists())
        self.assertTrue(obsolete.exists())

    def test_check_mode_does_not_write_candidate(self):
        self.write_archive({"skills/story-deslop/references/new.md": b"new\n"})
        result = prepare(self.archive, self.current, "v0.9.1", SHA, None)
        self.assertTrue(result["changed"])
        self.assertFalse(self.output.exists())

    def test_bootstrap_without_existing_snapshot(self):
        empty = self.directory / "empty"
        empty.mkdir()
        self.write_archive()
        self.assertTrue(prepare(self.archive, empty, "v0.9.0", SHA, self.output)["changed"])
        self.assertEqual(validate_layout(self.output)["files"], 102)

    def test_existing_output_is_never_overwritten(self):
        self.output.mkdir()
        (self.output / "keep.txt").write_bytes(b"keep")
        self.write_archive()
        with self.assertRaisesRegex(SnapshotError, "new directory"):
            self.prepare()
        self.assertEqual((self.output / "keep.txt").read_bytes(), b"keep")

    def test_output_inside_skills_is_rejected(self):
        self.output = self.current / "skills" / "candidate"
        self.write_archive()
        with self.assertRaisesRegex(SnapshotError, "inside current skills"):
            self.prepare()

    def test_missing_skill_blocks_output(self):
        self.write_archive(removed=[p for p in self.original if p.startswith("skills/story-deslop/")])
        with self.assertRaisesRegex(SnapshotError, "missing Skill"):
            self.prepare()
        self.assertFalse(self.output.exists())

    def test_missing_required_reference_blocks_output(self):
        self.write_archive(removed=["skills/story-long-write/references/workflow-chapter.md"])
        with self.assertRaisesRegex(SnapshotError, "missing local reference"):
            self.prepare()

    def test_missing_dynamic_dependency_blocks_output(self):
        self.write_archive(removed=["skills/story-long-write/scripts/wordcount_core.py"])
        with self.assertRaisesRegex(SnapshotError, "missing local reference"):
            self.prepare()

    def test_license_only_change_requires_manual_review(self):
        self.write_archive(license_data=self.license + b"\n")
        with self.assertRaisesRegex(SnapshotError, "LICENSE changed without Skill changes"):
            self.prepare()

    def test_joint_license_change_is_reported(self):
        self.write_archive({"skills/story-deslop/references/new.md": b"new\n"}, license_data=self.license + b"\n")
        self.assertTrue(self.prepare()["license_changed"])

    def test_missing_license_fails(self):
        self.write_archive(removed=["LICENSE"])
        with self.assertRaises(OSError):
            self.prepare()

    def test_changed_copyright_fails(self):
        self.write_archive(license_data=self.license.replace(b"oh-story-claudecode", b"somebody-else"))
        with self.assertRaisesRegex(SnapshotError, "license/attribution"):
            self.prepare()

    def test_truncated_mit_body_fails(self):
        self.write_archive(license_data=self.license.replace(b"FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.", b""))
        with self.assertRaisesRegex(SnapshotError, "MIT license body"):
            self.prepare()

    def test_private_file_blocks_candidate_emission(self):
        self.write_archive({"skills/story-deslop/.env": b"PRIVATE=synthetic\n"})
        with self.assertRaisesRegex(SnapshotError, "private artifact"):
            self.prepare()
        self.assertFalse(self.output.exists())

    def test_wrong_archive_commit_fails(self):
        self.write_archive()
        with self.assertRaisesRegex(SnapshotError, "archive root"):
            stage_archive(self.archive, self.output, "b" * 40)

    def test_unsafe_archive_paths(self):
        for raw in ("../escape", ARCHIVE_ROOT + "/skills/story-deslop/../../escape", "/absolute",
                    ARCHIVE_ROOT + "/skills/story-deslop/scripts/C:stream", ARCHIVE_ROOT + "/a\\b",
                    ARCHIVE_ROOT + "/skills/story-deslop/references/CON.md",
                    ARCHIVE_ROOT + "/skills/story-deslop/references/name. "):
            with self.subTest(raw=raw):
                entry = tarfile.TarInfo(raw)
                entry.size = 1
                self.write_archive(extras=[(entry, b"x")])
                with self.assertRaises(SnapshotError):
                    self.prepare()
                self.assertFalse(self.output.exists())

    def test_symlink_hardlink_and_special_files_are_rejected(self):
        for kind in (tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.FIFOTYPE, tarfile.CHRTYPE):
            with self.subTest(kind=kind):
                entry = tarfile.TarInfo(ARCHIVE_ROOT + "/skills/story-deslop/scripts/evil")
                entry.type = kind
                entry.linkname = "../../outside"
                self.write_archive(extras=[(entry, None)])
                with self.assertRaisesRegex(SnapshotError, "link/special"):
                    self.prepare()

    def test_unselected_upstream_alias_is_never_extracted(self):
        entry = tarfile.TarInfo(ARCHIVE_ROOT + "/.agents/skills")
        entry.type = tarfile.SYMTYPE
        entry.linkname = "../skills"
        self.write_archive({"skills/story-deslop/references/new.md": b"new\n"}, extras=[(entry, None)])
        self.prepare()
        self.assertFalse((self.output / ".agents").exists())

    def test_skill_root_link_is_rejected(self):
        entry = tarfile.TarInfo(ARCHIVE_ROOT + "/skills/story-deslop")
        entry.type = tarfile.SYMTYPE
        entry.linkname = "../somewhere"
        self.write_archive(extras=[(entry, None)])
        with self.assertRaisesRegex(SnapshotError, "directory replaced"):
            self.prepare()

    def test_duplicate_and_case_colliding_entries_are_rejected(self):
        for name in ("SKILL.md", "skill.md"):
            with self.subTest(name=name):
                entry = tarfile.TarInfo(ARCHIVE_ROOT + "/skills/story-deslop/" + name)
                entry.size = 1
                self.write_archive(extras=[(entry, b"x")])
                with self.assertRaisesRegex(SnapshotError, "colliding"):
                    self.prepare()

    def test_oversized_selected_asset_is_rejected(self):
        self.write_archive({"skills/story-deslop/references/large.md": b"a" * (MAX_FILE + 1)})
        with self.assertRaisesRegex(SnapshotError, "oversized"):
            self.prepare()

    def test_archive_never_executes_upstream(self):
        path = "skills/story-deslop/scripts/check-degeneration.js"
        self.write_archive({path: self.original[path] + b'\nthrow new Error("Do not execute during preparation");\n'})
        self.assertTrue(self.prepare()["changed"])

    def test_corrupt_current_snapshot_is_not_silently_repaired(self):
        (self.current / "skills/story-deslop/SKILL.md").write_bytes(b"corrupt")
        self.write_archive()
        with self.assertRaises(SnapshotError):
            self.prepare()

    def test_lock_without_skills_is_invalid_baseline(self):
        shutil.rmtree(self.current / "skills")
        self.write_archive()
        with self.assertRaisesRegex(SnapshotError, "lock exists without skills"):
            self.prepare()

    def test_pinned_metadata_validation(self):
        for tag, sha in (("main", SHA), ("v0.9.1-rc1", SHA), ("v0.9.0", "abc123")):
            with self.subTest(tag=tag, sha=sha), self.assertRaises(SnapshotError):
                make_lock(self.current, tag, sha)

    def test_release_resolution_uses_tag_commit_not_target_branch(self):
        urls = []
        def fake_download(url, destination):
            urls.append(url)
            value = ({"draft": False, "prerelease": False, "tag_name": "v0.9.0", "target_commitish": "main"}
                     if url.endswith("/latest") else {"sha": SHA})
            write_json(destination, value)
        with patch("sync_upstream.download", fake_download):
            self.assertEqual(resolve_release(self.directory), ("v0.9.0", SHA))
        self.assertTrue(urls[-1].endswith("/commits/v0.9.0"))

    def test_prerelease_and_draft_are_rejected(self):
        for field in ("draft", "prerelease"):
            def fake_download(url, destination):
                write_json(destination, {"draft": False, "prerelease": False, "tag_name": "v0.9.0", field: True})
            with self.subTest(field=field), patch("sync_upstream.download", fake_download):
                with self.assertRaisesRegex(SnapshotError, "stable"):
                    resolve_release(self.directory)


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="test-validation-", dir=ROOT / ".cache")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        shutil.copytree(ROOT / "skills", self.root / "skills")
        shutil.copyfile(ROOT / "LICENSE", self.root / "LICENSE")
        self.relock()

    def relock(self):
        write_json(self.root / "upstream-lock.json", make_lock(self.root, "v0.9.0", SHA))

    def test_third_skill_is_rejected(self):
        (self.root / "skills/third").mkdir()
        with self.assertRaisesRegex(SnapshotError, "exactly"):
            validate_layout(self.root)

    def test_frontmatter_name_mismatch_is_rejected(self):
        path = self.root / "skills/story-deslop/SKILL.md"
        path.write_bytes(path.read_bytes().replace(b"name: story-deslop", b"name: other"))
        with self.assertRaisesRegex(SnapshotError, "frontmatter name"):
            validate_layout(self.root)

    def test_byte_changes_and_missing_files_invalidate_lock(self):
        path = self.root / "skills/story-deslop/references/expression.md"
        path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
        with self.assertRaisesRegex(SnapshotError, "lock"):
            validate_layout(self.root)

    def test_deleted_file_invalidates_lock(self):
        (self.root / "skills/story-deslop/references/expression.md").unlink()
        with self.assertRaisesRegex(SnapshotError, "lock"):
            validate_layout(self.root)

    def test_lock_digest_tampering_is_rejected(self):
        path = self.root / "upstream-lock.json"
        value = json.loads(path.read_bytes())
        value["content_digest_sha256"] = "0" * 64
        write_json(path, value)
        with self.assertRaisesRegex(SnapshotError, "lock"):
            validate_layout(self.root)

    def test_reference_escape_and_missing_link_are_rejected(self):
        path = self.root / "skills/story-deslop/references/test.md"
        for link in ("../../story-long-write/SKILL.md", "missing.md", "%2e%2e/%2e%2e/outside.md", "C:/Users/private.md"):
            with self.subTest(link=link):
                path.write_text(f"[link]({link})\n", encoding="utf-8")
                with self.assertRaises(SnapshotError):
                    validate_references(self.root)

    def test_new_skill_route_requires_review(self):
        path = self.root / "skills/story-deslop/references/new.md"
        path.write_text("运行 /story-new-feature。\n", encoding="utf-8")
        with self.assertRaisesRegex(SnapshotError, "unreviewed Skill route"):
            validate_references(self.root)

    def test_unknown_python_dependency_requires_review(self):
        path = self.root / "skills/story-long-write/scripts/new.py"
        path.write_text("import third_party_package\n", encoding="utf-8")
        with self.assertRaisesRegex(SnapshotError, "unknown Python import"):
            validate_references(self.root)

    def test_unknown_javascript_dependency_requires_review(self):
        path = self.root / "skills/story-deslop/scripts/new.js"
        path.write_text("require('third-party');\n", encoding="utf-8")
        with self.assertRaisesRegex(SnapshotError, "unknown Node dependency"):
            validate_references(self.root)

    def test_dynamic_require_requires_review(self):
        path = self.root / "skills/story-deslop/scripts/new.js"
        path.write_text("require(process.argv[2]);\n", encoding="utf-8")
        with self.assertRaisesRegex(SnapshotError, "dynamic JS require"):
            validate_references(self.root)

    def test_credential_and_private_home_paths_are_detected(self):
        path = self.root / "skills/story-deslop/references/new.md"
        for data in (b"-----BEGIN PRIVATE KEY-----", b"ghp_" + b"a" * 36, b"C:\\Users\\someone\\secret"):
            with self.subTest(data=data):
                path.write_bytes(data)
                with self.assertRaises(SnapshotError):
                    validate_distribution_data(self.root)

    def test_unexpected_distribution_file_type_is_rejected(self):
        (self.root / "skills/story-deslop/references/config.env").write_bytes(b"not allowed")
        with self.assertRaisesRegex(SnapshotError, "unexpected asset type"):
            validate_distribution_data(self.root)

    def test_digest_is_order_independent_and_path_sensitive(self):
        self.assertEqual(digest({"b": b"2", "a": b"1"}), digest({"a": b"1", "b": b"2"}))
        self.assertNotEqual(digest({"a": b"bc"}), digest({"ab": b"c"}))
        self.assertNotEqual(digest({"a": b"1"}), digest({"a": b"1\r\n"}))

    def test_safe_path_rejects_windows_and_posix_aliases(self):
        for raw in ("a/../b", "a/./b", "a//b", "\\\\server\\share", "a/NUL.txt", "a/a.", "a/a ", "a/x:y"):
            with self.subTest(raw=raw), self.assertRaises(SnapshotError):
                safe_path(raw)


if __name__ == "__main__":
    unittest.main()
