#!/bin/bash

# Default values
LEVEL="ERROR"
PATTERN=""
SUMMARY=false

# Help message
usage() {
    echo "Usage: $0 [--level LEVEL] [--pattern PATTERN] [--summary] <log_file>"
    echo "  --level LEVEL    Filter by log level (e.g., ERROR, WARN, INFO). Default: ERROR"
    echo "  --pattern PATTERN Search for a specific regex pattern."
    echo "  --summary        Display a summary of log levels."
    exit 1
}

# Parse arguments
while [[ "$#" -gt 0 ]]; do
    case $1 in
        --level) LEVEL="$2"; shift ;;
        --pattern) PATTERN="$2"; shift ;;
        --summary) SUMMARY=true ;;
        -h|--help) usage ;;
        *) if [ -z "$LOG_FILE" ]; then LOG_FILE="$1"; else usage; fi ;;
    esac
    shift
done

# Validate log file
if [ -z "$LOG_FILE" ]; then
    echo "Error: No log file specified."
    usage
fi

if [ ! -f "$LOG_FILE" ]; then
    echo "Error: File '$LOG_FILE' not found."
    exit 1
fi

# Logic: Summary
if [ "$SUMMARY" = true ]; then
    echo "--- Log Level Summary ---"
    for lvl in ERROR CRITICAL WARN WARNING INFO DEBUG; do
        count=$(grep -ci "$lvl" "$LOG_FILE")
        echo "$lvl: $count"
    done
    exit 0
fi

# Logic: Pattern Search
if [ -n "$PATTERN" ]; then
    echo "--- Searching for pattern: $PATTERN ---"
    grep -Ei "$PATTERN" "$LOG_FILE" || echo "No matches found."
    exit 0
fi

# Logic: Level Filter
echo "--- Filtering by level: $LEVEL ---"
grep -Ei "$LEVEL" "$LOG_FILE" || echo "No entries found for level $LEVEL."
