"""Offline probe safeguards; actual installed DSH integration is an explicit smoke command."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from smoke_dsh import Asar, isolated_environment
from snapshot import SnapshotError


class ProbeTests(unittest.TestCase):
    def setUp(self):
        (ROOT / ".cache").mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix="test-dsh-probe-", dir=ROOT / ".cache")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.work = self.base / "isolated"
        self.work.mkdir()
        self.private = self.base / "private-canary"
        self.private.mkdir()
        self.canary = self.private / "canary.txt"
        self.canary.write_bytes(b"synthetic private canary")

    def node(self, code):
        self.assertIsNotNone(shutil.which("node"), "Node is already required by the project validation")
        env = {k: v for k, v in os.environ.items() if k.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT"}}
        env.update({"OH_STORY_DSH_PROBE_ROOT": str(self.work), "OH_STORY_DSH_PRIVATE_ROOTS": json.dumps([str(self.private)])})
        result = subprocess.run(["node", "--require", str(ROOT / "scripts/dsh_offline_guard.cjs"), "-e", code,
                                 str(self.private), str(self.base / "outside.txt")],
                                cwd=self.work, env=env, capture_output=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.canary.read_bytes(), b"synthetic private canary")
        return json.loads(result.stdout)

    def test_environment_redirects_all_user_roots_and_drops_credentials(self):
        before = dict(os.environ)
        with patch.dict(os.environ, {"SYNTHETIC_API_KEY": "not-inherited", "NODE_OPTIONS": "not-inherited", "DSH_HOME": "not-inherited"}):
            env = isolated_environment(self.work, self.base / "real-home-canary")
        self.assertEqual(dict(os.environ), before)
        self.assertNotIn("SYNTHETIC_API_KEY", env)
        self.assertNotIn("NODE_OPTIONS", env)
        for key in ("HOME", "USERPROFILE", "DSH_HOME", "DSH_AGENTS_HOME", "APPDATA", "LOCALAPPDATA", "TEMP", "TMP"):
            self.assertTrue(Path(env[key]).is_relative_to(self.work), key)
        self.assertEqual(env["ELECTRON_RUN_AS_NODE"], "1")

    def test_guard_allows_isolated_filesystem_work(self):
        result = self.node("const fs=require('node:fs'); fs.writeFileSync('allowed.txt','ok'); console.log(JSON.stringify({text:fs.readFileSync('allowed.txt','utf8'),guard:globalThis.__ohStoryDshGuard}));")
        self.assertEqual(result["text"], "ok")
        self.assertTrue(all(v == 0 for v in result["guard"].values()))

    def test_guard_blocks_protected_reads_and_native_realpath(self):
        result = self.node("const fs=require('node:fs'),p=require('node:path'); for(const fn of [()=>fs.readFileSync(p.join(process.argv[1],'canary.txt')),()=>fs.realpathSync.native(process.argv[1])]){try{fn();throw Error('allowed');}catch(e){if(!e.message.includes('Probe blocked'))throw e;}} console.log(JSON.stringify(globalThis.__ohStoryDshGuard));")
        self.assertEqual(result["protected_read_attempts"], 2)

    def test_guard_blocks_outside_writes_without_creating_them(self):
        result = self.node("const fs=require('node:fs'); try{fs.writeFileSync(process.argv[2],'forbidden');throw Error('allowed');}catch(e){if(!e.message.includes('Probe blocked'))throw e;} console.log(JSON.stringify(globalThis.__ohStoryDshGuard));")
        self.assertEqual(result["outside_write_attempts"], 1)
        self.assertFalse((self.base / "outside.txt").exists())

    def test_guard_blocks_network_and_subprocess_before_execution(self):
        result = self.node("for(const fn of [()=>fetch('https://example.invalid'),()=>require('node:https').get('https://example.invalid'),()=>require('node:net').connect(1),()=>require('node:child_process').execFileSync('never-executed')]){try{fn();throw Error('allowed');}catch(e){if(!e.message.includes('Offline probe forbids'))throw e;}} console.log(JSON.stringify(globalThis.__ohStoryDshGuard));")
        self.assertEqual(result["network_attempts"], 3)
        self.assertEqual(result["subprocess_attempts"], 1)

    def test_guard_blocks_promise_filesystem_writes(self):
        result = self.node("(async()=>{try{await require('node:fs/promises').writeFile(process.argv[2],'forbidden');throw Error('allowed');}catch(e){if(!e.message.includes('Probe blocked'))throw e;} console.log(JSON.stringify(globalThis.__ohStoryDshGuard));})();")
        self.assertEqual(result["outside_write_attempts"], 1)
        self.assertFalse((self.base / "outside.txt").exists())

    def asar(self, header, data=b"{}"):
        encoded = json.dumps(header).encode()
        path = self.work / "fixture.asar"
        path.write_bytes(struct.pack("<IIII", 4, len(encoded) + 8, len(encoded) + 4, len(encoded)) + encoded + data)
        return path

    def test_asar_reads_only_the_requested_metadata(self):
        path = self.asar({"files": {"package.json": {"size": 2, "offset": "0"}}})
        self.assertEqual(Asar(path).read("package.json"), b"{}")
        with self.assertRaises(KeyError):
            Asar(path).read("missing")

    def test_asar_rejects_unpacked_or_out_of_bounds_members(self):
        for entry in ({"unpacked": True, "size": 2}, {"size": 1000000, "offset": "0"}):
            with self.subTest(entry=entry):
                path = self.asar({"files": {"package.json": entry}})
                with self.assertRaises(SnapshotError):
                    Asar(path).read("package.json")

    def test_asar_rejects_unsupported_headers(self):
        path = self.work / "bad.asar"
        path.write_bytes(struct.pack("<IIII", 99, 16, 12, 8) + b"{}      ")
        with self.assertRaises(SnapshotError):
            Asar(path)


if __name__ == "__main__":
    unittest.main()
