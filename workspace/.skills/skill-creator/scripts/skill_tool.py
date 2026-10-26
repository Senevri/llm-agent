#!/usr/bin/env python3
"""Scaffold and validate skills.

  skill_tool.py new <name> "<description>"
  skill_tool.py validate [name]      # no name = validate all
Skills root: $SKILLS_ROOT, default .skills
"""
import os, re, sys
from pathlib import Path

ROOT = Path(os.getenv("SKILLS_ROOT", ".skills"))
NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
MAX_NAME, MAX_DESC = 64, 300  # DESC cap is stricter than the spec: catalog cost

TEMPLATE = """---
name: {name}
description: {desc}
---

# {title}

1.
"""

def frontmatter(text):
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        return None
    fm = {}
    for line in m.group(1).splitlines():
        if ":" in line and not line.startswith((" ", "\t")):
            k, v = line.split(":", 1)
            fm[k.strip()] = v.strip()
    return fm

def check(skill_dir: Path):
    errs = []
    md = skill_dir / "SKILL.md"
    if not md.is_file():
        return [f"{skill_dir.name}: missing SKILL.md"]
    text = md.read_text(encoding="utf-8")
    fm = frontmatter(text)
    if fm is None:
        return [f"{skill_dir.name}: no frontmatter (must start with ---)"]
    name, desc = fm.get("name", ""), fm.get("description", "")
    if name != skill_dir.name:
        errs.append(f"name '{name}' must match folder '{skill_dir.name}'")
    if not NAME_RE.match(name) or len(name) > MAX_NAME:
        errs.append("name must be lowercase-hyphenated, max 64 chars")
    if not desc:
        errs.append("description is empty")
    elif len(desc) > MAX_DESC:
        errs.append(f"description is {len(desc)} chars (max {MAX_DESC})")
    for link in re.findall(r"\]\((?!https?:|#)([^)\s]+)\)", text):
        if not (skill_dir / link).exists():
            errs.append(f"broken link: {link}")
    return [f"{skill_dir.name}: {e}" for e in errs]

def cmd_new(name, desc):
    if not NAME_RE.match(name) or len(name) > MAX_NAME:
        sys.exit("name must be lowercase-hyphenated, max 64 chars")
    if len(desc) > MAX_DESC:
        sys.exit(f"description too long ({len(desc)} > {MAX_DESC})")
    d = ROOT / name
    if d.exists():
        sys.exit(f"{d} already exists")
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(
        TEMPLATE.format(name=name, desc=desc, title=name.replace("-", " ").title()),
        encoding="utf-8")
    print(f"Created {d / 'SKILL.md'}. Edit it, then run: skill_tool.py validate {name}")

def cmd_validate(name=None):
    dirs = [ROOT / name] if name else sorted(p for p in ROOT.iterdir() if p.is_dir())
    errs = [e for d in dirs for e in check(d)]
    print("\n".join(errs) if errs else f"OK: {len(dirs)} skill(s) valid")
    sys.exit(1 if errs else 0)

if __name__ == "__main__":
    a = sys.argv[1:]
    if len(a) == 3 and a[0] == "new":
        cmd_new(a[1], a[2])
    elif a and a[0] == "validate" and len(a) <= 2:
        cmd_validate(a[1] if len(a) == 2 else None)
    else:
        sys.exit(__doc__)