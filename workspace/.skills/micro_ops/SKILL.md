---
name: micro_ops
description: atomic tools in script format
---


# Micro-Ops Skill
description: [Atomic tools]. [Use when you need to perform low-level, deterministic operations like text extraction, JSON parsing, or file checks without the overhead of complex shell commands.]
A collection of highly specialized, atomic tools designed to reduce the cognitive and computational load on an agent.

# Instructions
 - scripts/implementation.py contains small utility functions, implementations.TOOL_REGISTRY is a dict of the tools.


## Tool Definitions

### `grep <pattern> <input>`
Searches for a regex `pattern` within the provided `input`. If `input` is a file path, searches the file. Otherwise, searches the string.
- **Returns**: Matching lines or `None`.

### `json_get <key> <json_string>`
Extracts a value from a JSON string using a dot-notation key (e.g., `user.name`).
## When NOT to use

- When you need to perform complex transformations or multi-step workflows that require dynamic logic or external dependencies.
- When the task involves high-level reasoning or decision-making that requires context beyond the provided tools.
- **Returns**: The extracted value as a string, or `None`.

### `json_validate <json_string> <required_keys_json>`
Checks if a JSON string contains all specified required keys. `required_keys_json` must be a JSON array of strings (e.g., `["id", "status"]`).
- **Returns**: `Valid` or `Missing: <key1, key2>`.

### `count <type> <input>`
Counts occurrences of `type` (`lines`, `words`, `chars`) in the `input`.
- **Returns**: Integer count.

### `exists <path>`
Checks if a file or directory exists.
- **Returns**: `True` or `False`.

### `math <expression>`
Evaluates a simple mathematical expression.
- **Returns**: Resulting float/int or `Error`.

### `shell_report <stdout> <stderr> <exit_code>`
Provides a structured summary of a shell command execution.
- **Returns**: A summary containing status, exit code, and the last 5 lines of stdout/stderr.
## Verification checklist

- [ ] The skill provides the expected atomic operations (grep, json_get, json_validate, count, exists, math, shell_report).
- [ ] The tools handle edge cases (invalid JSON, missing files, malformed regex) gracefully.
- [ ] The tools are deterministic and produce consistent results.
- [ ] The tools are efficient and do not introduce significant overhead.


## Resources:
 - ´scripts/implementation.py´ -