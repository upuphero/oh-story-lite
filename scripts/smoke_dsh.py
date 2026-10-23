"""Probe the installed Windows DSH runtime, offline, entirely under .cache.

No profile is booted, no Agent or model is run, and real Skills/configuration
roots are blocked in the child processes. DSH modules remain in the installation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess

from manage_install import absolute, check_ancestors, manage
from snapshot import SnapshotError, inventory, require, write_json
from validate_layout import validate_layout

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = ("dsh", "dsh-desktop-host", "dsh-skill", "dsh-skill-filesystem", "dsh-tool-skill",
            "dsh-agent-preset-registry", "dsh-home-paths", "cordis", "dsh-tools", "dsh-system-prompt")


class Asar:
    """Read selected metadata/source bytes, without extracting or importing app code."""
    def __init__(self, path: Path):
        self.path = path
        with path.open("rb") as source:
            marker, header_size, _, json_size = struct.unpack("<IIII", source.read(16))
            require(marker == 4 and 0 < json_size < 16 * 1024 * 1024, "unsupported ASAR header")
            require(header_size >= json_size + 8, "invalid ASAR header length")
            self.header = json.loads(source.read(json_size))
            self.base = 8 + header_size

    def read(self, name: str) -> bytes:
        entry = self.header
        for part in name.split("/"):
            entry = entry["files"][part]
        require(not entry.get("unpacked") and "offset" in entry, f"expected a packed DSH module: {name}")
        size, offset = entry["size"], self.base + int(entry["offset"])
        require(0 <= size < 16 * 1024 * 1024 and offset + size <= self.path.stat().st_size, "invalid ASAR member bounds")
        with self.path.open("rb") as source:
            source.seek(offset)
            data = source.read(size)
        require(len(data) == size, "truncated ASAR member")
        return data


def hash_file(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as source:
        while data := source.read(1024 * 1024):
            result.update(data)
    return result.hexdigest()


def isolated_environment(work: Path, real_home: Path) -> dict[str, str]:
    retained = {"PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "OS", "PROCESSOR_ARCHITECTURE", "NUMBER_OF_PROCESSORS"}
    env = {k: v for k, v in os.environ.items() if k.upper() in retained}
    private = [real_home / ".agents", real_home / ".dsh",
               real_home / "AppData/Roaming/@deepseek-ai/dsh-desktop"]
    env.update({"HOME": str(work / "home"), "USERPROFILE": str(work / "home"),
                "APPDATA": str(work / "appdata"), "LOCALAPPDATA": str(work / "localappdata"),
                "TEMP": str(work / "temp"), "TMP": str(work / "temp"),
                "DSH_HOME": str(work / "home/.dsh"), "DSH_AGENTS_HOME": str(work / "home/.agents"),
                "ELECTRON_RUN_AS_NODE": "1", "OH_STORY_DSH_PROBE_ROOT": str(work),
                "OH_STORY_DSH_PRIVATE_ROOTS": json.dumps([str(p) for p in private])})
    return env


def run_child(executable: Path, script: Path, args: list[str], work: Path, env: dict, label: str) -> str:
    evidence = work / (label + "-guard.json")
    child_env = {**env, "OH_STORY_DSH_GUARD_REPORT": str(evidence)}
    result = subprocess.run([str(executable), "--expose-internals", "--require", str(ROOT / "scripts/dsh_offline_guard.cjs"),
                             str(script), *args], cwd=work / "workspace", env=child_env,
                            capture_output=True, encoding="utf-8", timeout=90)
    (work / (label + ".stdout")).write_text(result.stdout, encoding="utf-8")
    (work / (label + ".stderr")).write_text(result.stderr, encoding="utf-8")
    require(result.returncode == 0, f"DSH {label} failed: {result.stderr[-3000:]}")
    guard = json.loads(evidence.read_bytes())
    require(guard and all(value == 0 for value in guard.values()), f"DSH {label} attempted a forbidden operation")
    return result.stdout


def smoke_dsh(desktop: Path, work: Path) -> dict:
    desktop, work = absolute(desktop), absolute(work)
    require(os.name == "nt", "installed Desktop probe currently targets Windows")
    require(work.is_relative_to(ROOT / ".cache") and work != ROOT / ".cache", "probe work directory must be under this repository's .cache")
    check_ancestors(work)
    require(not work.exists(), "probe work directory must be new")
    validate_layout(ROOT)
    archive = desktop / "resources/app.asar"
    executable = desktop / "DeepSeek Harness.exe"
    require(executable.is_file() and archive.is_file(), "DSH Desktop executable/resources not found")
    asar = Asar(archive)
    archive_hash = hash_file(archive)
    desktop_metadata = json.loads(asar.read("package.json"))
    versions, modules = {}, {}
    for package in PACKAGES:
        prefix = f"dsh/node_modules/@deepseek-ai/{package}/"
        versions[package] = json.loads(asar.read(prefix + "package.json"))["version"]
        name = "lib/bin.js" if package == "dsh" else "lib/index.js"
        modules[package + "/" + name] = hashlib.sha256(asar.read(prefix + name)).hexdigest()
    original = inventory(ROOT)
    lock_before = (ROOT / "upstream-lock.json").read_bytes()
    work.mkdir(parents=True)
    for path in ("home/.dsh", "home/.agents", "appdata", "localappdata", "temp", "workspace/.git"):
        (work / path).mkdir(parents=True, exist_ok=True)
    manage("Install", work / "home/.agents/skills", ROOT)
    env = isolated_environment(work, Path(os.environ.get("USERPROFILE", str(Path.home()))))
    runtime = archive / "dsh"
    cli = runtime / "node_modules/@deepseek-ai/dsh-desktop-host/lib/cli.js"
    version = run_child(executable, cli, ["--version"], work, env, "version").strip()
    require(version == versions["dsh"], "CLI version differs from installed DSH metadata")
    help_text = run_child(executable, cli, ["--help"], work, env, "help")
    require("--profile <name>" in help_text and "--dump-config" in help_text, "unexpected installed CLI help")
    output = run_child(executable, ROOT / "scripts/dsh_discovery_probe.mjs", [str(runtime), str(work)], work, env, "discovery")
    discovery = json.loads(output)
    require(discovery.get("status") == "passed" and len(discovery.get("cases", [])) == 9, "incomplete DSH discovery checks")
    require(inventory(work / "home/.agents") == original, "shared-user test installation was changed")
    for loaded in discovery["loaded"]:
        raw = original[f"skills/{loaded['name']}/SKILL.md"]
        require(loaded["raw_skill_sha256"] == hashlib.sha256(raw).hexdigest(), "DSH loaded unexpected Skill bytes")
    require(inventory(ROOT) == original and (ROOT / "upstream-lock.json").read_bytes() == lock_before,
            "repository Skills or lock changed during probe")
    require(hash_file(archive) == archive_hash, "DSH installation changed during probe; rerun on a stable version")
    report = {"status": "passed", "test_kind": "installed DSH modules in a minimal isolated Cordis context",
              "desktop_version": desktop_metadata["version"], "cli_version": version,
              "package_versions": versions, "app_archive_sha256": archive_hash, "module_sha256": modules,
              "desktop_root": str(desktop), "work_directory": str(work), "discovery": discovery,
              "cli_guards": {label: json.loads((work / (label + "-guard.json")).read_bytes()) for label in ("version", "help")},
              "real_skills_installed": False, "profile_booted": False, "model_execution": False,
              "fallback_behavior": "missing preset runtime errors + loaded direct-execution contract; model obedience not tested"}
    write_json(work / "report.json", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--desktop-root", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = smoke_dsh(args.desktop_root, args.work_dir)
        print(json.dumps({"status": report["status"], "desktop_version": report["desktop_version"],
                          "cli_version": report["cli_version"], "runtime_cases": len(report["discovery"]["cases"]),
                          "report": str(absolute(args.work_dir) / "report.json"),
                          "automatic_model_fallback": "not tested; no model/Agent execution"}, indent=2))
        return 0
    except (SnapshotError, OSError, ValueError, TypeError, KeyError, struct.error, subprocess.SubprocessError) as exc:
        print(f"ERROR: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
