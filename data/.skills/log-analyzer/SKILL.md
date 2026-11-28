---
name: log-analyzer
description: Analyzes log files for errors, warnings, and specific patterns. Use this skill when you need to troubleshoot application logs, search for exceptions, or summarize log events.
compatibility: Requires grep, awk, and sed.
metadata:
  version: "1.0.0"
  category: "diagnostic"
---

# Log Analyzer Skill

This skill provides a structured approach to analyzing log files without loading entire files into the LLM context.

## Instructions

1. **Quick Scan for Errors**:
   To find all lines containing "ERROR" or "CRITICAL" in a file, use:
   `.skills/log-analyzer/scripts/analyze_logs.sh --level ERROR <log_file>`

2. **Search for Pattern**:
   To search for a specific keyword or regex pattern, use:
   `.skills/log-analyzer/scripts/analyze_logs.sh --pattern "keyword" <log_file>`

3. **Summarize Frequency**:
   To count occurrences of different log levels, use:
   `.skills/log-analyzer/scripts/analyze_logs.sh --summary <log_file>`

## Examples

**Input:**
`.skills/log-analyzer/scripts/analyze_logs.sh --level ERROR /var/log/syslog`

**Expected Output:**
A list of all lines containing "ERROR" in the specified log file, or a message if none are found.

**Input:**
`.skills/log-analyzer/scripts/analyze_logs.sh --summary /var/log/syslog`

**Expected Output:**
A count of ERROR, WARN, INFO, and DEBUG entries.
