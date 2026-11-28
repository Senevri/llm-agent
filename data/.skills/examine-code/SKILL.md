---
name: examine-code
description: Quickly examine unfamiliar codebases using structural searches, symbol references, language-aware grep patterns, and lightweight scripts. Use before modifying code or investigating unfamiliar functionality.
---

# Examine Code

## Purpose

Understand an unfamiliar codebase efficiently without reading every file or building heavyweight analysis tools.

Prefer structural discovery and targeted inspection over dumping entire files into context.

## Workflow

### 1. Establish project structure

Identify:
- Programming language(s)
- Project root and directory layout
- Entry points
- Build configuration and dependencies
- Tests and documentation

Useful commands:

```bash
ls -la
find . -maxdepth 2 -type f | sort
rg --files
```

Ignore generated files, build artifacts, virtual environments, and vendored dependencies where appropriate.

### 2. Inventory declarations

Use `rg` to locate classes, functions, methods, imports, and other declarations.

**Python**
```bash
rg -n '^\s*(class|def|async def) ' -g '*.py'
rg -n '^\s*(from .* import|import )' -g '*.py'
```

**JavaScript / TypeScript**
```bash
rg -n '^\s*(export )?(default )?(class|function|const|let) ' -g '*.{js,jsx,ts,tsx}'
rg -n '^\s*(import|export) ' -g '*.{js,jsx,ts,tsx}'
```

**C / C++**
```bash
rg -n '^\s*(class|struct|enum|namespace|typedef) ' -g '*.{c,cpp,h,hpp}'
rg -n '^\s*#\s*(include|define)' -g '*.{c,cpp,h,hpp}'
```

**Rust**
```bash
rg -n '^\s*(pub )?(struct|enum|trait|fn|impl|mod) ' -g '*.rs'
rg -n '^\s*(use|mod) ' -g '*.rs'
```

Adapt searches to the language and coding style. Regex inventories are approximate, not parsers.

### 3. Trace symbols

Find definitions and usages:

```bash
rg -n '\bSymbolName\b' .
```

Determine:
- Where is it defined?
- Who calls it?
- What does it call?
- What state does it read or modify?
- Is it overridden, wrapped, or re-exported?

Follow callers and dependencies only as far as necessary to understand the behavior.

### 4. Inspect targeted sections

Prefer reading relevant line ranges:

```bash
sed -n '100,180p' path/to/file
```

Avoid reading whole files unless they are small or the task requires it.

For Python, the standard library AST can provide more reliable declaration inventories than regex:

```bash
python - <<'PY'
import ast
from pathlib import Path

for path in Path(".").rglob("*.py"):
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        continue

    for node in ast.walk(tree):
        if isinstance(node, (ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            print(f"{path}:{node.lineno}: {node.name}")
PY
```

Use equivalent lightweight language tooling when available. Avoid installing dependencies just to perform basic inspection.

### 5. Understand behavior

Look beyond names and comments. Establish:

- Actual control flow
- Data transformations
- State ownership and lifecycle
- Error handling
- Configuration and defaults
- Persistence and serialization
- External interfaces
- Test coverage

Distinguish intended behavior from implemented behavior.

### 6. Before changing anything

Establish the source of the behavior before proposing modifications.

Check:
- Relevant callers and their assumptions
- Existing tests and fixtures
- Related implementations
- Whether apparently unusual behavior is intentional

Do not repair tests merely because they fail. Determine whether the code or the tests are wrong.

## Search principles

- Start broad, then narrow.
- Search by symbol rather than guessing filenames.
- Restrict searches by file type and directory.
- Prefer targeted excerpts over large output.
- Use scripts for repetitive inspection.
- Preserve filenames and line numbers in results.
- Avoid spending context on boilerplate or irrelevant generated code.

## Expected result

When examination is complete, be able to summarize:

1. Relevant files and entry points.
2. Important classes and functions.
3. How the relevant behavior flows through the code.
4. Dependencies and state involved.
5. Uncertainties or areas requiring further inspection.

Do not produce a comprehensive architecture report unless requested. The goal is to gather enough evidence to answer the actual question or make a safe, focused change.
