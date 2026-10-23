"""Run local static checks, offline tests and synthetic upstream CLI smoke checks.

No paid models, package installs, network calls, user Skill installation or real
novel files are used. Upstream execution belongs in a read-only CI job in M3.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from snapshot import SKILLS, SnapshotError, inventory, require, write_json
from validate_layout import validate_layout
from validate_references import validate_references

TOOLS_ROOT = Path(__file__).resolve().parents[1]
CACHE = TOOLS_ROOT / ".cache"


def run(command: list[str], expected: int = 0, cwd: Path | None = None, timeout: int = 60) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1"}
    result = subprocess.run(command, cwd=cwd or TOOLS_ROOT, env=env, capture_output=True,
                            encoding="utf-8", errors="strict", timeout=timeout)
    require(result.returncode == expected,
            f"expected exit {expected}, got {result.returncode}: {' '.join(command)}\n{result.stdout}\n{result.stderr}")
    return result


def validate_syntax(root: Path) -> dict:
    node = shutil.which("node")
    require(node is not None, "Node.js is required for local validation")
    counts = {"python": 0, "javascript": 0}
    for path, data in inventory(root).items():
        if path.endswith(".py"):
            compile(data, path, "exec")  # Syntax only: no imports, no __pycache__ in mirror.
            counts["python"] += 1
        elif path.endswith(".js"):
            run([node, "--check", str(root / path)])
            counts["javascript"] += 1
    for path in (TOOLS_ROOT / "scripts").glob("*.py"):
        compile(path.read_bytes(), str(path), "exec")
    for path in (TOOLS_ROOT / "scripts").iterdir():
        if path.suffix in {".js", ".cjs", ".mjs"}:
            run([node, "--check", str(path)])
    return counts


def validate_distribution_data(root: Path) -> dict:
    files = inventory(root)
    for relative, data in files.items():
        require(not any(p in {".env", ".aws", "credentials", "正文", "追踪", "大纲", "设定"}
                        for p in Path(relative).parts), f"private artifact in distribution: {relative}")
        require(Path(relative).suffix in {".md", ".py", ".js"},
                f"manual adaptation required: unexpected asset type: {relative}")
        text = data.decode("utf-8")
        require(not re.search(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|\bgh[pousr]_[A-Za-z0-9]{30,}", text),
                f"possible credential in {relative}")
        require(not re.search(r"[A-Za-z]:[\\/]Users[\\/][^\s{}<>]+|/Users/[^\s{}<>]+", text),
                f"personal absolute home path in {relative}")
    for name in (".env", "正文", "追踪", "大纲", "设定", ".active-book"):
        require(not (root / name).exists(), f"private root artifact: {name}")
    return {"scanned_files": len(files), "note": "High-signal checks only; manual review remains necessary before publication."}


def validate_samples(root: Path) -> dict:
    fixtures = TOOLS_ROOT / "tests" / "fixtures"
    cases = (("check-ai-patterns.js", "ai-patterns.md", "em-dash"),
             ("check-degeneration.js", "degeneration.md", "placeholder-leak"))
    checks = 0
    CACHE.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="oh-story-samples-", dir=CACHE) as temp:
        # Copy synthetic fixtures to isolate whitelist discovery from the repository.
        directory = Path(temp)
        for fixture in fixtures.glob("*.md"):
            shutil.copyfile(fixture, directory / fixture.name)
        originals = {p.name: p.read_bytes() for p in directory.iterdir()}
        for skill in SKILLS:
            for script, bad, finding in cases:
                command = ["node", str(root / "skills" / skill / "scripts" / script),
                           "--check", "--json", "--fail-on=blocking"]
                result = run(command + [str(directory / "clean.md")])
                require(json.loads(result.stdout)["findings"] == [], f"clean fixture generated findings: {skill}/{script}")
                result = run(command + [str(directory / bad)], expected=1)
                require(any(row.get("type") == finding and row.get("severity") == "blocking"
                            and row.get("line", 0) > 0 for row in json.loads(result.stdout)["findings"]),
                        f"missing expected blocking finding {finding}: {skill}/{script}")
                run(command + [str(directory / "missing.md")], expected=2)
                checks += 3
        require({p.name: p.read_bytes() for p in directory.iterdir()} == originals,
                "report-only detectors changed fixtures")
    return {"cli_cases": checks, "report_only_unchanged": True}


def validate_runtime(root: Path) -> dict:
    scripts = root / "skills" / "story-long-write" / "scripts"
    commands = 0
    CACHE.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="oh-story-runtime-", dir=CACHE) as temp:
        project = Path(temp)
        for task in ("world", "volume", "outline"):
            command = [sys.executable, str(scripts / "build_architect_brief.py"), "--project", str(project),
                       "--task", task, "--rules-only"]
            if task == "outline":
                command += ["--chapters", "1-2"]
            result = run(command)
            require(isinstance(json.loads(result.stdout), dict), "architect did not return JSON")
            commands += 1
        # Exercise local importlib dependencies and tracking views using invented test data.
        initial = {
            "schema_version": 1, "book_title": "自动化测试项目", "last_chapter": 0,
            "context": {"position": {"volume": "测试卷", "volume_start_chapter": 1,
                                      "story_time": "测试开始前", "scene": "测试室"},
                        "long_term_constraints": [], "active_character_names": [],
                        "continuity_risks": [], "recent_chapters": [], "next_chapter_commitments": []},
            "character_snapshots": {}, "foreshadow": [], "timeline_events": [],
        }
        write_json(project / "init.json", initial)
        run([sys.executable, str(scripts / "tracking_commit.py"), "init", "--project", str(project),
             "--input", str(project / "init.json")])
        run([sys.executable, str(scripts / "tracking_commit.py"), "check", "--project", str(project)])
        commands += 2
        # Missing private inputs must stop the assembler instead of producing prose.
        result = run([sys.executable, str(scripts / "build_writer_prompt.py"), "--project", str(project),
                      "--chapter", "1", "--out"], expected=2)
        require("组装中止" in result.stderr, "assembler did not explain missing inputs")
        require(not list(project.rglob("writer_prompt.md")), "assembler wrote a prompt despite missing inputs")
        commands += 1
        # Targeted exercise of the genre-card glob and author-memory query without a model.
        (project / "设定").mkdir()
        (project / "设定" / "题材定位.md").write_text("- 题材类型：都市日常\n", encoding="utf-8")
        code = ("import sys; from pathlib import Path; sys.path.insert(0,sys.argv[1]); "
                "from build_writer_prompt import match_genre_cards; "
                "assert match_genre_cards(Path(sys.argv[2])), 'no genre card found'")
        run([sys.executable, "-c", code, str(scripts), str(project)])
        result = run([sys.executable, str(scripts / "author_memory_commit.py"), "query", "--workspace", str(project),
                      "--book-root", str(project), "--kind", "prose_style"])
        require(isinstance(json.loads(result.stdout), dict), "author memory did not return JSON")
        commands += 2
        # Exercise storyctl's dynamic module loading and Node checker chain.
        for folder in ("大纲", "正文"):
            (project / folder).mkdir()
        shutil.copyfile(TOOLS_ROOT / "tests" / "fixtures" / "clean.md", project / "正文" / "第001章_测试.md")
        (project / "大纲" / "细纲_第001章.md").write_text("# 第1章 测试\n", encoding="utf-8")
        code = ("import sys; from pathlib import Path; sys.path.insert(0,sys.argv[1]); "
                "import storyctl; q=storyctl.check_blocking_quality(Path(sys.argv[2]),Path(sys.argv[3])); "
                "assert not q['tool_errors'], q")
        run([sys.executable, "-c", code, str(scripts), str(project / "大纲" / "细纲_第001章.md"),
             str(project / "正文" / "第001章_测试.md")])
        commands += 1
        result = run(["node", str(scripts / "check-outline-contract.js"), "--json",
                      str(project / "大纲" / "细纲_第001章.md")], expected=1)
        report = json.loads(result.stdout)
        require(report.get("ok") is False and report.get("checks"), "invalid outline not rejected")
        commands += 1
    return {"synthetic_cli_cases": commands, "dsh_discovery": "not tested", "model_writing": "not tested"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=TOOLS_ROOT)
    parser.add_argument("--skip-unit-tests", action="store_true", help="validate a candidate before importing it")
    parser.add_argument("--report-file", type=Path, help="write a machine-readable success report after all checks pass")
    args = parser.parse_args()
    root = args.root.resolve()
    try:
        report = {"layout": validate_layout(root), "references": validate_references(root),
                  "syntax": validate_syntax(root), "data": validate_distribution_data(root),
                  "samples": validate_samples(root), "runtime": validate_runtime(root)}
        if not args.skip_unit_tests:
            result = run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"], timeout=600)
            print(result.stderr, end="")
            match = re.search(r"Ran (\d+) tests? in", result.stderr)
            require(match is not None, "unit test count missing")
            report["unit_tests"] = {"status": "passed", "count": int(match.group(1))}
        else:
            report["unit_tests"] = {"status": "skipped", "count": 0}
        report.update({"schema_version": 1, "status": "passed"})
        if args.report_file:
            require(not args.report_file.exists(), "report output must not already exist")
            write_json(args.report_file, report)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        print("PASS: local validation complete")
        return 0
    except (SnapshotError, OSError, ValueError, SyntaxError, subprocess.TimeoutExpired) as exc:
        print(f"FAIL: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
