#!/bin/bash
# fs-search-rag/scripts/search.sh
# A wrapper to simplify RAG-lite retrieval stages.

usage() {
    echo "Usage: $0 <stage> <query> [options]"
    echo "Stages:"
    echo "  discover  - List files containing the query"
    echo "  refine    - Search with context (5 lines)"
    echo "  extract   - Search for precise matches (with PCRE2)"
    echo "  defs      - Search for definitions (class/def/func)"
    exit 1
}

if [ $# -lt 2 ]; then
    usage
fi

STAGE=$1
QUERY=$2
shift 2

case $STAGE in
    discover)
        rg -l "$QUERY" "$@"
        ;;
    refine)
        rg -C 5 "$QUERY" "$@"
        ;;
    extract)
        rg -P "$QUERY" "$@"
        ;;
    defs)
        # Matches 'def name', 'class name', 'func name' etc.
        rg -E "(def|class|func|void|int|float)\s+.*$QUERY" "$@"
        ;;
    *)
        usage
        ;;
esac
