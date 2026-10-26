# Ripgrep (rg) Flags Reference

## Search Control
- `-l`, `--files-with-matches`: Only print the names of files with matches.
- `-L`, `--files-without-match`: Only print the names of files without matches.
- `-v`, `--invert-match`: Invert match; only show lines that do NOT match.
- `-w`, `--word-regexp`: Match whole words only.
- `-i`, `--ignore-case`: Ignore case.
- `-S`, `--smart-case`: Ignore case unless the pattern contains an uppercase letter.

## Context Control
- `-C <NUM>`, `--context <NUM>`: Print NUM lines of output context.
- `-B <NUM>`, `--before-context <NUM>`: Print NUM lines of output before the match.
- `-A <NUM>`, `--after-context <NUM>`: Print NUM lines of output after the match.

## Filtering
- `-t <TYPE>`, `--type <TYPE>`: Search only files of a certain type (e.g., `py`, `js`, `cpp`).
- `-T <TYPE>`, `--type-not <TYPE>`: Skip files of a certain type.
- `-g <GLOB>`, `--glob <GLOB>`: Include/exclude files matching a glob pattern.
- `--hidden`: Search hidden files.
- `--no-ignore`: Do not respect `.gitignore`.

## Advanced/Regex
- `-U`, `--multiline`: Enable multiline searching.
- `-P`, `--pcre2`: Use PCRE2 regex engine (allows lookaheads, lookbehinds).
- `-o`, `--only-matching`: Only show the part of the line that matched.

## Performance/Stats
- `--stats`: Print search statistics.
- `--max-count <NUM>`: Stop after <NUM> matches.
