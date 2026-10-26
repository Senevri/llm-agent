---
name: handoff-management
description: Keeps task state in NOTES.md so work survives context trimming. Use at the start of every multi-step task and after each completed step.
---

# Handoff

Your conversation history can be trimmed at any time. NOTES.md is the source of truth.

1. At task start: if NOTES.md exists, read it and continue from "Next". Otherwise create it with:
   `# Goal` / `# Done` / `# Next` / `# Decisions and dead ends`
2. After each completed step: update Done and Next. One line each.
3. When something fails or you reject an approach: add it under Decisions and dead ends, with the reason.
4. If you're unsure what you were doing, re-read NOTES.md before acting.