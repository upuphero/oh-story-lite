"""Check local links, literal asset references, imports and reviewed dynamic dependencies.

This is a conservative static check, not a proof of all runtime paths. Dynamic
dependencies are listed in dependencies.json and exercised by validate_all.py.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
import urllib.parse
from pathlib import Path

from snapshot import SKILLS, SnapshotError, inventory, require

MANIFEST = Path(__file__).with_name("dependencies.json")
NODE_BUILTINS = {"fs", "path"}


def check_target(source: Path, base: Path, raw: str, boundary: Path) -> None:
    target = urllib.parse.unquote(raw.split("#", 1)[0])
    if not target:
        return
    require(not re.match(r"^[a-zA-Z]:|^[/\\]", target) and "\\" not in target,
            f"absolute/unsafe local reference in {source.name}: {raw}")
    resolved = (base / target).resolve()
    require(resolved.is_relative_to(boundary.resolve()),
            f"manual adaptation required: reference escapes Skill in {source.name}: {raw}")
    require(resolved.exists(), f"missing local reference in {source.name}: {raw}")


def validate_references(root: Path) -> dict:
    files = inventory(root)
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    checked = 0
    warnings: set[str] = set()
    for key, targets in manifest["runtime_dependencies"].items():
        source = root / "skills" / key
        require(source.is_file(), f"reviewed dynamic entry point missing: {key}")
        base = root / "skills" / key.split("/", 1)[0]
        for target in targets:
            check_target(source, base, target, base)
            checked += 1
    for relative, data in files.items():
        source = root / relative
        base = root / "skills" / relative.split("/")[1]
        text = data.decode("utf-8")
        if source.suffix == ".md":
            links = re.findall(r"\[[^\]\n]*\]\(<?([^\s)>]+)>?(?:\s+[^)]*)?\)", text)
            # Reference-style Markdown links are also local dependencies.
            links += re.findall(r"^\s*\[[^\]]+\]:\s*<?([^\s>]+)", text, re.M)
            for target in links:
                if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target) and not re.match(r"^[a-zA-Z]:", target):
                    continue
                check_target(source, source.parent, target, base)
                checked += 1
            # Commands and backticks also carry hard asset references.
            for target in re.findall(r"(?<![\w/-])(?:references|scripts)/[\w./-]+\.(?:md|py|js)", text):
                check_target(source, base, target, base)
                checked += 1
            # Bare filenames used in prose are resolved against the reference/script directory.
            for target in re.findall(r"(?<![\w/.-])([A-Za-z][A-Za-z0-9_-]*\.(?:md|py|js))(?![\w.-])", text):
                folder = "references" if target.endswith(".md") else "scripts"
                if target == "SKILL.md":
                    check_target(source, base, target, base)
                else:
                    # Project artifacts use Chinese names; ASCII .md references here are bundled methods.
                    if target in manifest["non_asset_names"]:
                        continue
                    check_target(source, base / folder, target, base)
                checked += 1
            routes = set(re.findall(r"(?<![\w-])story-[a-z]+(?:-[a-z]+)*(?![\w-]|\.(?:md|py|js|toml))", text)) - set(SKILLS)
            for route in routes:
                if (base / "references" / (route + ".md")).is_file():
                    continue
                if route + "/v1" in text:
                    continue  # Script JSON schema identifiers.
                # Custom agent story-* names are runtime capabilities, not third Skills.
                if route in {"story-architect", "story-explorer", "story-continuity", "story-researcher", "story-deployed"}:
                    continue
                require(route in manifest["optional_skill_routes"],
                        f"manual adaptation required: unreviewed Skill route {route} in {relative}")
                warnings.add(f"optional route (not bundled): {route}")
        elif source.suffix in {".py", ".js"}:
            key = source.relative_to(root / "skills").as_posix()
            if source.suffix == ".py":
                tree = ast.parse(text, filename=relative)
                local_modules = {p.stem for p in source.parent.glob("*.py")}
                for node in ast.walk(tree):
                    imports = []
                    if isinstance(node, ast.Import):
                        imports = [a.name.split(".")[0] for a in node.names]
                    elif isinstance(node, ast.ImportFrom):
                        imports = [(node.module or "").split(".")[0]]
                    for module in imports:
                        require(module in sys.stdlib_module_names or module in local_modules,
                                f"manual adaptation required: unknown Python import {module} in {relative}")
                        if module in local_modules:
                            check_target(source, source.parent, module + ".py", base)
                            checked += 1
                literals = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
            else:
                modules = re.findall(r"\brequire\(\s*['\"]([^'\"]+)['\"]\s*\)", text)
                require(len(modules) == len(re.findall(r"\brequire\(", text)),
                        f"manual adaptation required: dynamic JS require in {relative}")
                for module in modules:
                    if module.startswith("."):
                        check_target(source, source.parent, module, base)
                    else:
                        require(module in NODE_BUILTINS, f"unknown Node dependency: {module} in {relative}")
                    checked += 1
                literals = set(re.findall(r"['\"]([^'\"\n]+)['\"]", text))
            for literal in literals:
                if re.fullmatch(r"[A-Za-z0-9_.-]+\.(?:py|js)", literal):
                    check_target(source, source.parent, literal, base)
                    checked += 1
                elif re.fullmatch(r"references/[A-Za-z0-9_./-]+\.md", literal):
                    optional = manifest["optional_missing_assets"].get(key, {})
                    if literal in optional and not (base / literal).exists():
                        warnings.add(f"optional asset: {key}: {literal}: {optional[literal]}")
                    else:
                        check_target(source, base, literal, base)
                    checked += 1
                elif source.name == "build_architect_brief.py" and re.fullmatch(r"[a-z][a-z0-9-]+\.md", literal):
                    check_target(source, base / "references", literal, base)
                    checked += 1
    return {"checked_references": checked, "warnings": sorted(warnings)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    try:
        print(json.dumps(validate_references(args.root.resolve()), ensure_ascii=False, indent=2))
        return 0
    except (SnapshotError, OSError, ValueError, SyntaxError) as exc:
        print(f"ERROR: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
