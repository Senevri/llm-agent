---
name: fs-search-rag
description: Implements "RAG-lite" (Retrieval-Augmented Generation) strategies for filesystem search using ripgrep. Use this skill when you need to locate information across a large codebase, find definitions, or extract contextual chunks of code/text without a vector database.
compatibility: Requires ripgrep (rg).
---

# FS-Search-RAG: Filesystem Retrieval Strategies

This skill transforms a vague information need into a targeted retrieval process using `ripgrep`. Instead of reading entire files, use a multi-stage retrieval pipeline.

## Retrieval Pipeline

### Stage 1: Broad Discovery
Find which files are likely to contain the answer.
- **Keyword Search**: `rg "keyword" --stats`
- **File List**: `rg -l "keyword"` (Returns only filenames)
- **Type Filtering**: `rg -t py "keyword"` (Search only Python files)

### Stage 2: Targeted Refinement
Narrow down the search within the discovered files.
- **Definition Search**: Search for patterns like `class Name`, `def Name`, `const Name`.
- **Contextual Search**: Use `-C 5` to see 5 lines of context around the match.
- **Multiline Search**: Use `-U` (multiline) for patterns spanning multiple lines.

### Stage 3: Precision Extraction
Extract the exact block needed.
- **Exact Match**: `rg "exact pattern" -A 10` (Match and 10 lines after).
- **Negative Filter**: `rg "keyword" | rg -v "noise"` (Remove irrelevant matches).

## Recommended Patterns

| Goal | Command | Note |
| --- | --- | --- |
| Find definition | `rg "def \w*Keyword\w*"` | Finds function definitions containing Keyword |
| Find usages | `rg "Keyword\("` | Finds where a function is called |
| Search in config | `rg "Keyword" -g "*.yaml" -g "*.json"` | Limits search to config files |
| Find multi-line block | `rg -U "start_pattern\n.*end_pattern"` | Requires PCRE2 |

## When NOT to use this skill
- When you already know the exact file path.
- When the codebase is so small that reading all files is faster.
- When you need semantic search (meaning-based) and textual keywords are insufficient.

For detailed ripgrep flags, see [ripgrep reference](references/RIPGREP_FLAGS.md).
