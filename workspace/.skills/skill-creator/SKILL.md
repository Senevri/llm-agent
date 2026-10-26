---
name: skill-creator
description: Use when the user asks for a new skill, or when you've hit the same problem twice and want to capture the fix. Scaffolds and validates skills with a script.
---

# Skill Creator

1. Scaffold: `python .skills/skill-creator/scripts/skill_tool.py new <name> "<description>"`
2. Edit the new SKILL.md. Keep it under ~40 lines: numbered steps, concrete commands, no principles.
3. Move anything exact (conversions, checks) into `scripts/` and call it from the steps.
4. Validate: `python .skills/skill-creator/scripts/skill_tool.py validate <name>`. Fix every error.
5. The description must say *when* to use the skill, in under 300 chars.