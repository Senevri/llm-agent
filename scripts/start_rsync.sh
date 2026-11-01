#!/bin/bash
(
    while true; do
        sleep 30
        rsync -rlq -O \
        --no-perms --no-owner --no-group \
        --modify-window=3 \
        --exclude='.git' \
        --exclude='node_modules' \
        --exclude='__pycache__' \
        --exclude='.mypy_cache' \
        --exclude='.pytest_cache' \
        --exclude='.venv' \
        /workspace/ /mnt/workspace/backup &> /dev/null
    done
) &

exec "$@"