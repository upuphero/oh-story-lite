"""Offline checks of the privilege boundary and local sync job replay (no GitHub writes)."""

from __future__ import annotations

import hashlib
import io
import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from ci_sync import prepare_job
from lint_workflows import check_pins
from snapshot import SnapshotError, inventory, make_lock, write_json
from smoke_install import smoke_install
from sync_artifact import (apply_bundle, bundle_digest, pack_bundle, replace_snapshot,
                           unpack_bundle, verify_checkout)
from validate_layout import validate_layout
from validate_references import validate_references

SHA = "b" * 40


def test_report(root: Path) -> dict:
    """Synthetic report for envelope unit tests; actual validation is replayed separately."""
    files = inventory(root)
    return {"schema_version": 1, "status": "passed", "layout": validate_layout(root),
            "references": validate_references(root),
            "syntax": {"python": sum(p.endswith(".py") for p in files),
                       "javascript": sum(p.endswith(".js") for p in files)},
            "samples": {"cli_cases": 12, "report_only_unchanged": True},
            "runtime": {"synthetic_cli_cases": 10}, "unit_tests": {"status": "passed", "count": 44}}


def git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", "-c", "core.autocrlf=false", "-c", "core.hooksPath=.no-hooks",
                             "-c", "user.name=Local tests", "-c", "user.email=tests@example.invalid", *args],
                            cwd=root, check=True, capture_output=True, encoding="utf-8")
    return result.stdout.strip()


class ArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (ROOT / ".cache").mkdir(exist_ok=True)
        cls.fixture = tempfile.TemporaryDirectory(prefix="actions-fixture-", dir=ROOT / ".cache")
        cls.template = Path(cls.fixture.name) / "baseline"
        shutil.copytree(ROOT / "skills", cls.template / "skills")
        for name in ("LICENSE", "upstream-lock.json", ".gitignore", ".gitattributes"):
            shutil.copyfile(ROOT / name, cls.template / name)
        (cls.template / "README.md").write_bytes(b"protected readme\n")
        (cls.template / "prompts").mkdir()
        (cls.template / "prompts/custom.md").write_bytes(b"protected prompt\n")
        (cls.template / ".github/workflows").mkdir(parents=True)
        (cls.template / ".github/workflows/ci.yml").write_bytes(b"protected workflow\n")
        git(cls.template, "init", "-b", "main")
        git(cls.template, "add", "--all")
        git(cls.template, "commit", "--no-gpg-sign", "-m", "Local fixture only")
        cls.base = git(cls.template, "rev-parse", "HEAD")

    @classmethod
    def tearDownClass(cls):
        cls.fixture.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="test-actions-", dir=ROOT / ".cache")
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.current = self.directory / "current"
        shutil.copytree(self.template, self.current)
        self.candidate = self.directory / "candidate"
        shutil.copytree(ROOT / "skills", self.candidate / "skills")
        shutil.copyfile(ROOT / "LICENSE", self.candidate / "LICENSE")
        self.new_path = "skills/story-deslop/references/sync-fixture.md"
        (self.candidate / self.new_path).write_bytes(b"Synthetic sync fixture.\n")
        self.relock()
        self.report = self.directory / "validation.json"
        write_json(self.report, test_report(self.candidate))
        self.artifact = self.directory / "snapshot.tar"
        self.body = self.directory / "body.md"
        self.metadata = self.directory / "metadata.json"

    def relock(self):
        write_json(self.candidate / "upstream-lock.json", make_lock(self.candidate, "v0.9.1", SHA))

    def pack(self):
        return pack_bundle(self.candidate, self.report, self.artifact)

    def apply(self, sha256=None, base=None):
        return apply_bundle(self.current, self.artifact, sha256 or bundle_digest(self.artifact),
                            base or self.base, self.body, self.metadata)

    def write_source_archive(self, candidate=None):
        root = candidate or self.candidate
        source = self.directory / "upstream.tar.gz"
        files = {**inventory(root), "LICENSE": (root / "LICENSE").read_bytes()}
        with tarfile.open(source, "w:gz") as archive:
            for path, data in files.items():
                member = tarfile.TarInfo(f"oh-story-claudecode-{SHA}/{path}")
                member.size = len(data)
                archive.addfile(member, io.BytesIO(data))
        return source

    def rewrite_bundle(self, extra=None, replacements=None):
        with tarfile.open(self.artifact, "r:") as source:
            files = {m.name: source.extractfile(m).read() for m in source if m.isfile()}
        files.update(replacements or {})
        self.artifact.unlink()
        with tarfile.open(self.artifact, "w") as output:
            for name, data in files.items():
                member = tarfile.TarInfo(name)
                member.size = len(data)
                output.addfile(member, io.BytesIO(data))
            if extra is not None:
                member, data = extra
                output.addfile(member, io.BytesIO(data) if data is not None else None)

    def test_sealed_artifact_roundtrip_preserves_all_bytes(self):
        sha256 = self.pack()
        root, report = unpack_bundle(self.artifact, sha256, self.directory / "unpacked")
        self.assertEqual(inventory(root), inventory(self.candidate))
        self.assertEqual(report["layout"], validate_layout(self.candidate))

    def test_apply_changes_only_the_allowlist_and_prepares_pr(self):
        self.pack()
        result = self.apply()
        self.assertTrue(result["changed"])
        for name, data in (("README.md", b"protected readme\n"), ("prompts/custom.md", b"protected prompt\n"),
                           (".github/workflows/ci.yml", b"protected workflow\n")):
            self.assertEqual((self.current / name).read_bytes(), data)
        self.assertEqual(inventory(self.current), inventory(self.candidate))
        body = self.body.read_text(encoding="utf-8")
        for required in ("v0.9.1", SHA, "1 added", "Rollback:", "44 offline tests", "Dependency review:"):
            self.assertIn(required, body)
        changed = git(self.current, "status", "--porcelain")
        self.assertNotIn("README", changed)
        self.assertNotIn(".github", changed)

    def test_apply_propagates_deletions(self):
        obsolete = self.current / "skills/story-deslop/references/obsolete.md"
        obsolete.write_bytes(b"old\n")
        lock = json.loads((self.current / "upstream-lock.json").read_bytes())
        write_json(self.current / "upstream-lock.json", make_lock(self.current, lock["release_tag"], lock["commit_sha"]))
        git(self.current, "add", "--all")
        git(self.current, "commit", "--no-gpg-sign", "-m", "Synthetic obsolete file")
        self.pack()
        self.apply(base=git(self.current, "rev-parse", "HEAD"))
        self.assertFalse(obsolete.exists())
        self.assertIn("D skills/story-deslop/references/obsolete.md", self.body.read_text(encoding="utf-8"))

    def test_same_content_new_tag_does_not_modify_checkout_or_lock(self):
        (self.candidate / self.new_path).unlink()
        self.relock()
        write_json(self.report, test_report(self.candidate))
        before = (self.current / "upstream-lock.json").read_bytes()
        self.pack()
        self.assertFalse(self.apply()["changed"])
        self.assertFalse(self.body.exists())
        self.assertEqual((self.current / "upstream-lock.json").read_bytes(), before)
        self.assertEqual(git(self.current, "status", "--porcelain"), "")

    def test_bundle_digest_mismatch_leaves_checkout_unchanged(self):
        self.pack()
        with self.assertRaisesRegex(SnapshotError, "SHA-256 mismatch"):
            self.apply(sha256="0" * 64)
        self.assertEqual(git(self.current, "status", "--porcelain"), "")

    def test_archive_cannot_overwrite_workflows_or_maintenance_code(self):
        for path in ("snapshot/.github/workflows/pwn.yml", "snapshot/scripts/evil.py", "snapshot/README.md",
                     "snapshot/skills/third/SKILL.md", "../escape", "snapshot/skills/story-deslop/../../escape"):
            with self.subTest(path=path):
                if self.artifact.exists():
                    self.artifact.unlink()
                self.pack()
                member = tarfile.TarInfo(path)
                member.size = 1
                self.rewrite_bundle(extra=(member, b"x"))
                with self.assertRaises(SnapshotError):
                    self.apply()
                self.assertEqual(git(self.current, "status", "--porcelain"), "")

    def test_bundle_symlink_hardlink_and_special_entries_are_rejected(self):
        for kind in (tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.FIFOTYPE):
            with self.subTest(kind=kind):
                if self.artifact.exists():
                    self.artifact.unlink()
                self.pack()
                member = tarfile.TarInfo("snapshot/skills/story-deslop/references/evil.md")
                member.type = kind
                member.linkname = "../../README.md"
                self.rewrite_bundle(extra=(member, None))
                with self.assertRaisesRegex(SnapshotError, "links/directories/special"):
                    self.apply()

    def test_duplicate_bundle_entry_is_rejected(self):
        self.pack()
        member = tarfile.TarInfo("snapshot/LICENSE")
        member.size = 1
        self.rewrite_bundle(extra=(member, b"x"))
        with self.assertRaisesRegex(SnapshotError, "duplicate"):
            self.apply()

    def test_report_must_match_the_sealed_snapshot(self):
        report = test_report(self.candidate)
        report["layout"]["content_digest_sha256"] = "0" * 64
        write_json(self.report, report)
        with self.assertRaisesRegex(SnapshotError, "snapshot mismatch"):
            self.pack()

    def test_skipped_unit_tests_cannot_be_sealed(self):
        report = test_report(self.candidate)
        report["unit_tests"] = {"status": "skipped", "count": 0}
        write_json(self.report, report)
        with self.assertRaisesRegex(SnapshotError, "unit tests"):
            self.pack()

    def test_missing_detector_coverage_cannot_be_sealed(self):
        report = test_report(self.candidate)
        report["samples"]["cli_cases"] = 0
        write_json(self.report, report)
        with self.assertRaisesRegex(SnapshotError, "detector"):
            self.pack()

    def test_report_tampering_is_rechecked_by_write_job(self):
        self.pack()
        report = test_report(self.candidate)
        report["status"] = "failed"
        self.rewrite_bundle(replacements={"validation.json": json.dumps(report).encode()})
        with self.assertRaisesRegex(SnapshotError, "successful validation"):
            self.apply()
        self.assertEqual(git(self.current, "status", "--porcelain"), "")

    def test_candidate_file_tampering_is_rejected_even_with_matching_bundle_digest(self):
        self.pack()
        self.rewrite_bundle(replacements={"snapshot/" + self.new_path: b"modified after validation\n"})
        with self.assertRaisesRegex(SnapshotError, "lock"):
            self.apply()

    def test_write_job_never_runs_upstream_code(self):
        path = self.candidate / "skills/story-deslop/scripts/check-degeneration.js"
        path.write_bytes(path.read_bytes() + b'\nthrow new Error("must not run in write job");\n')
        self.relock()
        write_json(self.report, test_report(self.candidate))
        self.pack()
        real_run = subprocess.run
        def only_git(command, **kwargs):
            self.assertEqual(command[0], "git", "write job tried to execute a candidate script")
            return real_run(command, **kwargs)
        with patch("sync_artifact.subprocess.run", side_effect=only_git):
            self.assertTrue(self.apply()["changed"])

    def test_default_branch_drift_blocks_application(self):
        self.pack()
        with self.assertRaisesRegex(SnapshotError, "default branch advanced"):
            self.apply(base="a" * 40)
        self.assertEqual(git(self.current, "status", "--porcelain"), "")

    def test_dirty_checkout_blocks_application(self):
        (self.current / "README.md").write_bytes(b"uncommitted\n")
        self.pack()
        with self.assertRaisesRegex(SnapshotError, "must be clean"):
            self.apply()

    def test_existing_metadata_outputs_are_not_overwritten(self):
        self.body.write_bytes(b"keep\n")
        self.pack()
        with self.assertRaisesRegex(SnapshotError, "metadata outputs"):
            self.apply()
        self.assertEqual(self.body.read_bytes(), b"keep\n")

    def test_failed_move_restores_the_previous_snapshot(self):
        before = inventory(self.current)
        original_rename = Path.rename
        candidate_root = self.candidate
        def fail_once(path, target):
            if path == candidate_root / "skills/story-deslop":
                raise OSError("synthetic move failure")
            return original_rename(path, target)
        with patch.object(Path, "rename", fail_once):
            with self.assertRaisesRegex(OSError, "synthetic move failure"):
                replace_snapshot(self.current, self.candidate, self.directory / "backup")
        self.assertEqual(inventory(self.current), before)

    def test_prepare_noop_skips_runtime_and_artifact(self):
        source = self.write_source_archive(self.current)
        work = self.directory / "work"
        with patch("ci_sync.subprocess.run") as execute:
            result = prepare_job(self.current, work, source, "v0.9.1", SHA)
        self.assertFalse(result["changed"])
        execute.assert_not_called()
        self.assertFalse((work / "snapshot.tar").exists())

    def test_prepare_failure_never_seals_an_artifact(self):
        source = self.write_source_archive()
        work = self.directory / "work"
        with patch("ci_sync.subprocess.run", side_effect=subprocess.CalledProcessError(2, "validation")):
            with self.assertRaises(subprocess.CalledProcessError):
                prepare_job(self.current, work, source, "v0.9.1", SHA)
        self.assertFalse((work / "snapshot.tar").exists())

    def test_prepare_changed_candidate_runs_full_validation_before_sealing(self):
        source = self.write_source_archive()
        work = self.directory / "work"
        def fake_validation(command, **kwargs):
            self.assertIn("--report-file", command)
            self.assertNotIn("--skip-unit-tests", command)
            candidate = Path(command[command.index("--root") + 1])
            write_json(Path(command[command.index("--report-file") + 1]), test_report(candidate))
        with patch("ci_sync.subprocess.run", side_effect=fake_validation) as execute:
            result = prepare_job(self.current, work, source, "v0.9.1", SHA)
        execute.assert_called_once()
        self.assertTrue(result["changed"])
        self.assertEqual(result["bundle_sha256"], bundle_digest(work / "snapshot.tar"))

    def test_isolated_discovery_copies_exact_bytes_without_real_home(self):
        result = smoke_install(self.current)
        self.assertEqual(result["skills"], ["story-deslop", "story-long-write"])
        self.assertFalse(result["real_home_modified"])


class WorkflowGuardTests(unittest.TestCase):
    """Focused regression guards; actionlint performs the actual YAML/expression parsing."""

    def test_every_action_is_reviewed_and_sha_pinned(self):
        self.assertEqual(check_pins(), 13)

    def test_write_job_is_gated_and_contains_no_upstream_execution(self):
        text = (ROOT / ".github/workflows/sync-upstream.yml").read_text(encoding="utf-8")
        read, write = text.split("  create-update-pr:", 1)
        self.assertIn("contents: read", read)
        self.assertNotIn("contents: write", read)
        self.assertIn("needs.prepare-and-validate.outputs.changed == 'true'", write)
        self.assertIn("github.event.repository.default_branch", write)
        self.assertIn("contents: write", write)
        self.assertIn("pull-requests: write", write)
        for forbidden in ("validate_all.py", "ci_sync.py", "node ", "npm ", "pip ", "skills/"):
            commands = "\n".join(line for line in write.splitlines() if line.startswith("          python") or line.startswith("          --"))
            self.assertNotIn(forbidden, commands)
        self.assertIn("--expected-base-sha", write)
        self.assertIn("--expected-sha256", write)

    def test_pr_branch_scope_and_manual_merge_are_fixed(self):
        text = (ROOT / ".github/workflows/sync-upstream.yml").read_text(encoding="utf-8")
        self.assertIn("branch: bot/sync-oh-story", text)
        self.assertIn("cancel-in-progress: false", text)
        self.assertIn("cron: '23 9 * * *'", text)
        self.assertNotIn("enable-auto-merge", text)
        self.assertNotIn("git push", text)
        self.assertEqual(text.count("persist-credentials: false"), 2)

    def test_ci_covers_pull_requests_main_and_windows(self):
        text = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        for required in ("pull_request:", "branches: [main]", "windows-latest", "ubuntu-latest", "scripts/smoke_install.py"):
            self.assertIn(required, text)
        self.assertNotIn("contents: write", text)


if __name__ == "__main__":
    unittest.main()
