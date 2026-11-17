---
name: pi-subagents
description: Delegate implementation and independent read-only reviews to Pi workers when the user or project instructions call for Pi delegation.
---

# Delegate to Pi workers

The lead owns task decomposition, interfaces, integration, final verification, and all work with TASKS.md. Delegate when independent work can proceed in parallel, needs specialized expertise, or benefits from independent review. Handle small fixes and tightly coupled changes directly when briefing, waiting, and integration would cost more than doing the work.

Give each worker the project root, relevant files and conventions, allowed edits, deliverable, acceptance criteria, and checks. Assign disjoint write scopes when workers share a checkout. If the project has a virtual environment, make sure the workers run everything under that.

## Launch commands

Use the launcher arguments below as written. Set the child process working directory to the project root. Keep the extension paths quoted and use forward slashes.

For inline prompts, pass the prompt as one literal argument and apply the current shell's escaping rules. Prefer a UTF-8 brief file for multiline text or shell metacharacters. Replace <prompt> with a single quoted "@<absolute-brief-path>" argument so Pi reads the contents without the shell interpreting them.

### Full access for implementation

```bash
pi --no-extensions --extension builtin:codemode --extension "C:/Users/arttu/.pi/agent/extensions/rtk.ts" --extension "C:/Users/arttu/.pi/agent/extensions/pi-budget.ts" --extension "C:/Users/arttu/.pi/agent/git/github.com/DietrichGebert/ponytail" --extension "C:/Users/arttu/.pi/agent/npm/node_modules/pi-codemode-toggle" --extension "C:/Users/arttu/.pi/agent/npm/node_modules/pi-llama-cpp" --extension "C:/Users/arttu/.pi/agent/npm/node_modules/pi-prefix-cache-compaction" --mode text --no-session --tools +codemode --tools +grep --tools +find --tools +ls --no-skills --no-mcp --thinking medium --model <model> -p <prompt>
```

### Read-only access for reviews and audits

The launcher exposes only read, grep, find, and ls. Keep --no-context-files and explicitly point reviewers to the relevant AGENTS.md files and project conventions in the brief. Ask reviewers to read those files before assessing conformance. Leave fixes to the implementation owner.

```bash
pi --no-extensions --extension "C:/Users/arttu/.pi/agent/extensions/rtk.ts" --extension "C:/Users/arttu/.pi/agent/extensions/pi-budget.ts" --extension "C:/Users/arttu/.pi/agent/npm/node_modules/pi-llama-cpp" --mode text --no-session --no-skills --no-mcp --no-context-files --thinking medium --tools read,grep,find,ls --append-system-prompt "You are in read-only mode. Complete your tasks purely in read-only mode." --model <model> -p <prompt>
```

## Suggested main roles

- Core implementation uses `mistral/zai-glm-5-3` for shared interfaces, complex changes, and specialist tasks that reach the retry limit.
- Specialist implementation uses `mistral/deepseek-v4-1-flash-1017` for bounded coding or optimization.
- Utility work uses `mistral/zai-glm-5-3-flash` for scoped tests, maintenance, or documentation. Use the read-only launcher for utility reviews.
- Independent verification uses `mistral/mistral-large-4` with the read-only launcher to check high-risk plans or audit integrated changes.

Don't stick to these roles without exceptions, they are merely suggestions. All models, including mistral/mistral—large—4 are very capable and can do development work. The main point is to have a separate agent review another's work to get an independent opinion.

## Role definition System prompts

Use `--append-system-prompt "<role-prompt>"` (can be used multiple times) to add a short role definition for the sub-agent. Use these templates, modify them as you see fit, or write your own.

### Plan auditor

You are the project's Plan auditor. Review the orchestrator’s plan against the request and the current project state. Make no edits. Flag missing requirements, unstated assumptions, dependency or ownership conflicts, and acceptance checks that would fail to prove completion. Rank findings by impact and suggest concrete changes to the plan.

### Implementation worker

You are the project's Implementation worker. Implement the assigned change within your write scope. Follow project conventions and preserve shared interfaces. If a contract needs to change, flag it to the lead before editing across that boundary. Run scoped checks and report changed files, results, and remaining gaps. Own `filename.py` and its tests.

### Read-only reviewer

You are the project's Static code reviewer. Review the assigned code, its callers, and relevant tests. Make no edits. Report actionable findings first, with severity, file and line, user impact, and a suggested fix. If you find no issues, state what you reviewed and what you could not verify.

### UI expert

You are the project's UI expert. Implement the assigned UI changes using the project’s existing patterns. Check the normal workflow, keyboard interaction, focus, and relevant empty and error states. Keep automated GUI tests isolated from the user’s desktop. Report what you verified visually and what you verified through tests.

### Test engineer

You are the project's Test engineer. Write focused tests for the assigned behavior and plausible regressions. Use deterministic fixtures and temporary data. Bound waits and clean up processes, files, and windows even when tests fail. Report the commands, results, and any behavior that still needs manual verification.

### Security auditor

You are the project's Security auditor. Review the assigned code and configuration in read-only mode. Trace trust boundaries, permissions, sensitive data, and unsafe defaults. Report findings with severity, location, impact, and a practical mitigation. Distinguish confirmed issues from hypotheses and use non-invasive checks.

### Documentation writer

You are the project's Documentation writer. Write or update only the assigned documentation. Verify commands, paths, defaults, and behavior against the current code. Explain the user workflow in plain language and state practical limits where they matter. Flag any claims you could not verify.

### Docstring writer

You are the project's Python docstring writer. Write or update only the assigned Python files' docstrings. Make sure the current ones match current implementation.

# Type hint writer

You are the project's Type hint writer. Add comprehensive, accurate type hints to the provided Python modules without altering their runtime logic or behavior.

## Run workers and collect results

Start independent workers as separate background processes. Give each a task ID, a timeout appropriate to the work, and separate stdout and stderr logs in a scratch directory. Keep process handles and record exit codes. On timeout, stop the worker and any child processes before reassigning its write scope. Inspect logs on timeout or a nonzero exit. A zero exit still requires a complete report and review of the result.

A failed attempt is a timed-out run, a nonzero exit, or a result that misses the acceptance criteria. Diagnose the failure and retry once when there is a concrete correction. With --no-session, each run starts fresh. Supply the full brief again with the prior error, log or diff references, and the current workspace state. After two failed attempts, escalate specialist work to the core implementation worker or have the lead take over.

## Worker reports

Implementation workers report files changed and what changed, commands run and their results, checks skipped, and open issues. Reviewers report findings with severity, file and line, impact, and suggested correction. If there are no findings, state what was reviewed and any gaps.

The lead inspects the combined diff, resolves findings, and runs the checks for the integrated result.
