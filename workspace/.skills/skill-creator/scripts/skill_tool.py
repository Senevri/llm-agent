
---

### 2. The Upgraded Python Script (`skill_tool.py`)
Replace your existing script with this version. It includes a **much better template** that guides the LLM, and the validator now actively checks for the presence of `## Instructions` and `## Description` sections, giving the LLM actionable feedback if it forgets them.

```python
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
MAX_NAME, MAX_DESC = 64, 300

TEMPLATE = """---
name: {name}
description: {desc}
---

# {title}

## Description
<Briefly explain what this skill does and when to use it.>

## Instructions
1. <Concrete, actionable step 1>
2. <Concrete, actionable step 2>
3. <If complex logic is needed, reference a script in the `scripts/` folder>

## Resources
- `scripts/`: <Add helper scripts here if needed>
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
        return [f"{skill_dir.name}: no frontmatter (must start with ---\\n...\\n---\\n)"]

    name, desc = fm.get("name", ""), fm.get("description", "")

    if name != skill_dir.name:
        errs.append(f"name '{name}' in frontmatter must match folder name '{skill_dir.name}'")
    if not NAME_RE.match(name) or len(name) > MAX_NAME:
        errs.append("name must be lowercase-hyphenated, max 64 chars")
    if not desc:
        errs.append("description is empty")
    elif len(desc) > MAX_DESC:
        errs.append(f"description is {len(desc)} chars (max {MAX_DESC})")

    # Content validation: Ensure the LLM actually wrote the required sections
    if "## Instructions" not in text:
        errs.append("missing '## Instructions' section")
    if "## Description" not in text:
        errs.append("missing '## Description' section")

    # Broken link check
    for link in re.findall(r"\]\((?!https?:|#)([^)\s]+)\)", text):
        if not (skill_dir / link).exists():
            errs.append(f"broken link: {link}")

    return [f"{skill_dir.name}: {e}" for e in errs]

def cmd_new(name, desc):
    if not NAME_RE.match(name) or len(name) > MAX_NAME:
        sys.exit("Error: name must be lowercase-hyphenated, max 64 chars")
    if len(desc) > MAX_DESC:
        sys.exit(f"Error: description too long ({len(desc)} > {MAX_DESC})")

    d = ROOT / name
    if d.exists():
        sys.exit(f"Error: {d} already exists")

    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(
        TEMPLATE.format(name=name, desc=desc, title=name.replace("-", " ").title()),
        encoding="utf-8")

    # Create an empty scripts dir for convenience
    (d / "scripts").mkdir(exist_ok=True)

    print(f"Created {d / 'SKILL.md'}.")
    print(f"1. Edit it to add concrete steps under '## Instructions'.")
    print(f"2. Run: python .skills/skill-creator/scripts/skill_tool.py validate {name}")

def cmd_validate(name=None):
    dirs = [ROOT / name] if name else sorted(p for p in ROOT.iterdir() if p.is_dir())
    if not dirs or not dirs[0].exists():
        sys.exit(f"Error: Skill directory not found.")

    errs = [e for d in dirs for e in check(d)]
    if errs:
        print("VALIDATION FAILED:")
        print("\n".join(f"  - {e}" for e in errs))
        print("\nFix the errors in SKILL.md and run validate again.")
        sys.exit(1)
    else:
        print(f"OK: {len(dirs)} skill(s) valid")
        sys.exit(0)

if __name__ == "__main__":
    a = sys.argv[1:]
    if len(a) == 3 and a[0] == "new":
        cmd_new(a[1], a[2])
    elif a and a[0] == "validate" and len(a) <= 2:
        cmd_validate(a[1] if len(a) == 2 else None)
    else:
        print(__doc__)
        sys.exit(1)