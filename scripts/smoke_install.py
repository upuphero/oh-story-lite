"""Copy and discover exactly two Skills in an isolated home; never touch the real home."""

import json
import re
import shutil
import tempfile
from pathlib import Path

from snapshot import SKILLS, inventory, require
from validate_layout import validate_layout

ROOT = Path(__file__).resolve().parents[1]


def smoke_install(root: Path) -> dict:
    validate_layout(root)
    cache = ROOT / ".cache"
    cache.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="skill-discovery-", dir=cache) as temp:
        agents = Path(temp) / "home" / ".agents"
        skills = agents / "skills"
        skills.mkdir(parents=True)
        for name in SKILLS:
            shutil.copytree(root / "skills" / name, skills / name)
        require(inventory(agents) == inventory(root), "isolated installation differs from distribution")
        discovered = []
        for directory in sorted(skills.iterdir()):
            text = (directory / "SKILL.md").read_text(encoding="utf-8")
            require(re.search(r"^name: " + re.escape(directory.name) + r"$", text, re.M) is not None,
                    "installed metadata not discoverable")
            discovered.append(directory.name)
        require(set(discovered) == set(SKILLS), "unexpected installed Skill")
    return {"skills": discovered, "bytes_preserved": True, "real_home_modified": False,
            "dsh_runtime_discovery": "not tested"}


if __name__ == "__main__":
    print(json.dumps(smoke_install(ROOT), indent=2))
