# Skill: skill_creator

## Description
Use this tool when the user asks to create a new skill, or when you notice a recurring pattern of errors/steps that should be codified into a reusable skill.

## Instructions
When creating a new skill, you MUST follow this exact workflow:

1. **Scaffold**: Run `python .skills/skill-creator/scripts/skill_tool.py new <name> "<description>"`
   - `<name>`: lowercase, hyphenated, max 64 chars (e.g., `prose_craft`).
   - `<description>`: A concise, <300 char explanation of *when* to use the skill.
2. **Draft the Skill**: Edit the generated `<name>/SKILL.md`. A valid skill MUST have:
   - `## Description`: 1-2 sentences on what it does.
   - `## Instructions`: Numbered, concrete, actionable steps. No vague principles.
   - `## Resources` (Optional): Paths to any helper scripts in the `scripts/` folder.
3. **Extract Logic**: If a step requires exact code, regex, or complex shell commands, move it to `<name>/scripts/helper.py` (or `.sh`) and reference it in the instructions. Do not put large code blocks in the SKILL.md.
4. **Validate**: Run `python .skills/skill-creator/scripts/skill_tool.py validate <name>`.
   - If it fails, read the error output, fix the `SKILL.md`, and re-run until it says "OK".
5. **Confirm**: Once valid, inform the user the skill is ready and briefly summarize its purpose.

## Resources
[example of a valid structure](references/example.md)
[full agentskill specification](references/specification.md)