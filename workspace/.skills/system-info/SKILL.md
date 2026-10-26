---
name: system-info
description: Collects and summarizes system information including OS, CPU, memory, and disk usage. Use this skill when you need to understand the environment's resource constraints or specifications.
compatibility: Requires bash and standard linux utilities (df, free, uname).
metadata:
  version: "1.0.0"
  category: "utility"
---

# System Info Skill

This skill provides a structured way to gather essential system information.

## Instructions

1. To get a quick summary of the system, run the primary script:
   `.skills/system-info/scripts/collect_info.sh`

2. For detailed reference on what each piece of information means, see [the reference guide](references/REFERENCE.md).

## Examples

**Input:**
`./.skills/system-info/scripts/collect_info.sh`

**Expected Output:**
A formatted report containing:
- OS version
- CPU architecture
- Memory usage
- Disk space availability
