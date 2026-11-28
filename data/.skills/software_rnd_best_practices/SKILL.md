# Software R&D Best Practices for Python

## Overview
This skill provides concise guidance on modern software research and development (R&D) best practices for Python, focusing on **KISS**, **DRY**, **TDD**, **version control**, **modularity**, and **functional programming**. It emphasizes practicality and modularity, ensuring only relevant bits are loaded when needed.

---
name: python-rnd
description: Practical guidance for Python software development and research. Use when implementing, modifying, debugging, testing, or evaluating Python code, particularly during exploratory R&D.
---

## Instructions

### 1. Inspect Before Changing

- Inspect the existing project structure, relevant source files, dependencies, and conventions before making changes.
- Check the existing tests and project configuration before introducing new tools or patterns.
- Inspect Git status before modifying files. Preserve unrelated changes and existing user work.
- Follow the project's established architecture unless there is a concrete reason to change it.
- Ask for clarification when a consequential design decision cannot be resolved from the available context.

### 2. Keep Changes Focused

- Prefer the smallest change that solves the actual problem.
- Follow KISS: avoid unnecessary abstractions, dependencies, configuration, and indirection.
- Follow DRY when duplication represents genuinely shared behavior. Do not introduce abstractions merely to eliminate superficially similar code.
- Keep modules cohesive and interfaces explicit.
- Prefer pure functions for logic that benefits from predictable inputs and outputs. Use state and side effects where they simplify the design.
- Do not create files, directories, frameworks, or example implementations without a concrete need.

### 3. Verify Behavior

- Identify the expected behavior before implementing a change.
- Write focused tests for important behavior, including relevant edge cases.
- Use test-driven development when appropriate; do not treat writing tests first as a ritual detached from the task.
- Run the relevant tests after changes and report failures honestly.
- For numerical or experimental code, verify the implementation against simple cases with known answers before trusting complex results.
- Distinguish implementation errors from limitations of the underlying approach.

### 4. Treat R&D as an Experiment

When investigating an uncertain technical approach:

1. State the hypothesis or question being investigated.
2. Establish a baseline or simpler alternative for comparison.
3. Choose measurable evaluation criteria.
4. Change as few variables as practical between experiments.
5. Record relevant inputs, parameters, dependencies, random seeds, and results to make findings reproducible.
6. Compare observed results against the baseline.
7. Report limitations, unexpected behavior, and alternative explanations.

Do not confuse a successful demonstration on one example with evidence of general effectiveness. Test generalization when it matters to the research question.

### 5. Manage Dependencies and Environments

- Inspect the existing dependency declarations and environment configuration before installing packages.
- Use the project's existing package and environment manager. Do not mix management approaches unnecessarily.
- Add dependencies only when they provide meaningful value over existing capabilities.
- Keep dependency declarations reproducible and avoid modifying the system Python environment.
- Verify that commands run in the intended environment.

### 6. Maintain Code Quality

- Follow the project's existing style and naming conventions.
- Use clear names, focused functions, and appropriate error handling.
- Add type annotations and documentation where they improve clarity, correctness, or maintainability.
- Prefer standard-library functionality when it adequately solves the problem.
- Introduce linters, formatters, type checkers, and pre-commit hooks when justified by project needs; do not install or configure every available tool by default.

### 7. Protect and Review Work

- Avoid overwriting existing files, configuration, data, or experimental results without justification.
- Before finishing, review the diff for unintended changes.
- Remove temporary artifacts created during the task when safe to do so.
- Do not claim tests passed, experiments succeeded, or behavior was verified unless the corresponding checks were actually performed.

### 8. Report Results Clearly

Summarize:
- What changed and why.
- What verification was performed and its outcome.
- Any remaining limitations, failures, or uncertainties.
- The most useful next step, when applicable.

Keep reports proportional to the task. Do not bury a small fix under a lengthy explanation.

## References

Consult local reference material only when it is relevant to the task.

- `references/testing.md` — Testing strategies, test isolation, regression testing, and test-driven development.
- `references/experimentation.md` — Experimental design, baselines, metrics, reproducibility, and interpreting results.
- `references/packaging.md` — Python environments, dependency management, and project configuration.
- [references and key principles](references/key_principles.md)
- [example project structure](references/example_project_structure.md)
These reference files are optional. If a referenced file does not exist, do not assume its contents or create a replacement unless the task requires it. Follow the project's existing conventions when no applicable reference is available.


## Tools and Libraries

| Tool/Library       | Purpose                                                                 |
|--------------------|--------------------------------------------------------------------------|
| `pytest`           | Testing framework for TDD.                                               |
| `mypy`             | Static type checking.                                                     |
| `ruff`             | Fast Python linter.                                                       |
| `black`            | Code formatter for consistent style.                                      |
| `isort`            | Sort imports alphabetically.                                                |
| `Git`              | Version control system.                                                   |
| `pre-commit`       | Automate code quality checks before commits.                               |
| `asyncio`          | Asynchronous programming for I/O-bound tasks.                             |

```

## References
For deeper dives, refer to the following resources:
1. [Python Packaging Authority](https://packaging.python.org/)
2. [Real Python - Best Practices](https://realpython.com/tutorials/best-practices/)
3. [Google Python Style Guide](https://google.github.io/styleguide/pyguide.html)
4. [Python Functional Programming HOWTO](https://docs.python.org/3/howto/functional.html)
5. [Python Asyncio Documentation](https://docs.python.org/3/library/asyncio.html)

## Scripts
For hands-on examples, check the `scripts/` directory:
- `tdd_example.py`: Test-Driven Development example.
- `functional_programming_example.py`: Functional programming principles.
- `modularity_example.py`: Modular project structure.
- `type_hints_example.py`: Type hints and static typing.
- `error_handling_example.py`: Error handling best practices.
- `asyncio_example.py`: Asynchronous programming with `asyncio`.
- `pre_commit_example.py`: Pre-commit hooks setup.

---