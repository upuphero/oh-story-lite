"""Validate distribution boundaries, upstream metadata and byte integrity."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from snapshot import SKILLS, SnapshotError, inventory, make_lock, plain_directory, regular_file, require


def validate_layout(root: Path) -> dict:
    skills = root / "skills"
    require(skills.is_dir() and plain_directory(skills), "missing/linked skills directory")
    require({p.name for p in skills.iterdir()} == set(SKILLS), "skills/ must contain exactly the two allowed directories")
    files = inventory(root)
    for name in SKILLS:
        base = root / "skills" / name
        require((base / "SKILL.md").is_file(), f"missing {name}/SKILL.md")
        text = (base / "SKILL.md").read_text(encoding="utf-8")
        front = re.match(r"\A---\r?\n(.*?)\r?\n---(?:\r?\n|$)", text, re.S)
        require(front is not None, f"missing frontmatter: {name}")
        names = re.findall(r"^name:\s*([^\r\n]+)", front.group(1), re.M)
        require(names == [name], f"frontmatter name must match directory: {name}")
        for directory in ("references", "scripts"):
            require((base / directory).is_dir() and any((base / directory).rglob("*")),
                    f"missing/empty {name}/{directory}")
    for name in ("LICENSE", "upstream-lock.json"):
        require((root / name).is_file() and regular_file(root / name), f"missing/linked {name}")
    license_text = (root / "LICENSE").read_text(encoding="utf-8")
    require(all(s in license_text for s in (
        "MIT License", "Copyright (c) 2025-2026 oh-story-claudecode", "Permission is hereby granted, free of charge",
        "The above copyright notice and this permission notice shall be included",
        'THE SOFTWARE IS PROVIDED "AS IS"', "IN NO EVENT SHALL THE")), "MIT license/attribution incomplete")
    # Whitespace may vary in a reviewed future license, but the complete MIT body must survive.
    mit_body = '''Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:
The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.
THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.'''
    require(" ".join(mit_body.split()) in " ".join(license_text.split()), "MIT license body incomplete or modified")
    lock = json.loads((root / "upstream-lock.json").read_text(encoding="utf-8"))
    require(isinstance(lock, dict), "lock must be an object")
    expected = make_lock(root, lock.get("release_tag", ""), lock.get("commit_sha", ""))
    require(lock == expected, "upstream-lock.json does not match snapshot bytes/schema")
    return {"files": len(files), "skill_counts": {name: sum(p.startswith(f"skills/{name}/") for p in files)
                                                  for name in SKILLS},
            "content_digest_sha256": expected["content_digest_sha256"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    try:
        print(json.dumps(validate_layout(args.root.resolve()), indent=2))
        return 0
    except (SnapshotError, OSError, ValueError, TypeError) as exc:
        print(f"ERROR: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
