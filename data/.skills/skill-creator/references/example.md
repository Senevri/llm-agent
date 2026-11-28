## Example of a Valid Skill Structure
```markdown
---
name: my_new_skill
description: Use this to format data when the user provides raw CSV input.
---

# My New Skill

## Description
Formats raw CSV data into a clean, structured Markdown table.

## Instructions
1. Read the user's raw CSV input.
2. Run `python scripts/format_csv.py --input data.csv --output formatted.md`.
3. Read `formatted.md` and present it to the user.

## Resources
- `scripts/format_csv.py`: Handles the complex parsing logic.
```