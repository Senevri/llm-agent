---
name: good-coding-habits
description: >
  Enforces disciplined software development: plan before coding, write tests
  first, verify failures, implement, verify success, and audit the result.
  Use whenever writing or modifying code in this project.
---

# Good Coding Habits

## Overview

A disciplined workflow for writing, testing, and auditing code changes.
Follow these steps whenever you add or modify functionality.

## Workflow

### 1. Plan

Before writing any code:

- State the goal in one sentence.
- List the files that will change.
- Describe the public interface of new functions/classes.
- Note any dependencies or breaking changes.
- Keep the plan under 20 lines.

### 2. Audit the Plan

Review your own plan:

- Does it solve the stated goal without over-engineering?
- Are the interfaces minimal and well-scoped?
- Is there a simpler approach you're missing?
- Will existing tests still pass?

If any answer is unclear, revise the plan before proceeding.

### 3. Write Tests First

- Create or extend tests in the appropriate `tests/` file.
- Tests should be deterministic where possible.
- Use fixtures for shared setup (e.g., goblin instances).
- Tests must be runnable with `pytest tests/`.

### 4. Verify Tests Fail

- Run the new tests **before** implementing anything.
- Confirm they fail with the expected error.
- If they pass already, the test is not testing anything.

### 5. Implement

- Write the minimum code to make the tests pass.
- Follow existing code style and naming conventions.
- Add docstrings to every public function.
- Do not refactor unrelated code in the same commit.

### 6. Verify Tests Pass

- Run the full test suite: `pytest tests/ -v`.
- Confirm all tests pass, including the new ones.
- If any existing test fails, investigate before proceeding.

### 7. Audit the Result

After everything passes:

- Re-read the original plan. Did you deliver what was promised?
- Scan the diff for dead code, copy-paste, or over-engineering.
- Check that docstrings match the implementation.
- Consider edge cases not covered by tests.
- If the change is non-trivial, update `plans.md` or `README.md`.

## Principles

- **Small commits.** One logical change per commit.
- **Tests are the spec.** If it's not tested, it doesn't exist.
- **Refactor after, not during.** Make it work, make it right, make it fast.
- **Ask before guessing.** If you're unsure about a requirement, ask.
