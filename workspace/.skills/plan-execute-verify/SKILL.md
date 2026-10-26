---
name: plan-execute-verify
description: Use at the start of any task needing more than 3 tool calls, and again before reporting it complete. Makes you define runnable checks first and run them before finishing.
---

# Plan, Execute, Verify

1. **Plan** (3-7 steps, written to NOTES.md). Give each step a check that a command can run:
   - Good: `pytest -q` exits 0 / `test -s out.csv` / `grep -c ERROR app.log` prints 0
   - Bad: "works correctly", "looks right"
2. **Execute** one step at a time. Update NOTES.md after each.
3. **Verify** with a *different* command than the one that did the work. A command not erroring is not evidence. Read the actual output.
4. **If a check fails twice**, stop retrying the same fix. Write the failure under "Dead ends" in NOTES.md and choose a different approach.
5. **Before the final answer**, re-run every check once and report each result.