---
name: good-coding-habits
description: >
  When writing, modifying, or refactoring code — especially adding new
  methods, changing existing ones, or preparing for pickling/caching —
  follow this workflow: plan before coding, write tests first, verify
  they fail, implement, verify they pass, then clean up.
---

# Good Coding Habits

## When to Apply

Use this skill whenever you are about to write or modify code in the
WordGoblin project, particularly when:

- Adding a new method or class
- Refactoring an existing function
- Changing a public API
- Preparing data structures for pickling / caching
- Introducing a new module or goblin

## Workflow

### 1. Plan

Before touching any code, state your plan explicitly:

- What changes are needed and why
- Which files will be created or modified
- What the public interface of any new method / class will look like
- What the existing tests cover and what gaps exist

Keep the plan short (5–10 lines). Revisit it after implementation.

### 2. Audit Existing Tests

- Read the relevant test file(s) in `tests/`
- Identify which tests already cover the area you're changing
- Note any gaps — untested edge cases, missing fixtures, or dead code

### 3. Write Tests First (When Possible)

- Add test(s) that express the desired behaviour
- If the behaviour is new, the test should **fail** before implementation
- If you are fixing a bug, add a regression test that reproduces it

Run the tests and confirm they fail (or that the regression test fails).

### 4. Implement

- Write the minimal code needed to make the tests pass
- Do not over-engineer; resist the urge to refactor unrelated code
- Keep changes focused on the stated plan

### 5. Verify

- Run the full test suite: `pytest tests/`
- Confirm all previously passing tests still pass
- Confirm the new / regression test now passes

### 6. Clean Up

- Remove any temporary print statements or debug code
- Ensure docstrings are present on new public functions
- Check that imports are ordered and unused imports removed
- Commit or note the changes

## Project-Specific Notes

### Pickling / Caching

When preparing a goblin for pickling:

- Ensure all mutable state is serialisable (no file handles, locks, etc.)
- Document which attributes are loaded vs. rebuilt at unpickle time
- If a cache is rebuilt (e.g. `build_sampling_cache()`), make that
  explicit in the class docstring

### Goblin Architecture

- Each goblin should expose a simple, inspectable interface
- Goblins operate on shared data structures; they do not need to
  understand everything
- Prefer composition over inheritance

### Testing Conventions

- Use `pytest` fixtures for shared goblin instances
- Name test functions `test_<method>_<scenario>`
- Keep tests deterministic where possible; seed `random` when needed

## Quick Checklist

- [ ] Plan stated before coding
- [ ] Existing tests audited
- [ ] New / regression tests written and confirmed failing
- [ ] Implementation done
- [ ] All tests pass
- [ ] No debug / temporary code left behind
- [ ] Pickle readiness checked (if applicable)
