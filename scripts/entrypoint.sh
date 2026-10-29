#!/bin/sh
echo "running entrypoint.sh"
# set -eu

# # Host is ground truth: populate the container workspace first.
# rsync -rlt --no-perms --no-owner --modify-window=3 \
#   --exclude='.git' --exclude='node_modules' \
#   /mnt/workspace/ /workspace/

# # Then persist container-side changes to the host.
# (
#     while true; do
#         sleep 30
#         rsync -rl --no-perms --no-owner --modify-window=3 \
#           --exclude='.git' --exclude='node_modules' --exclude='__pycache__' \
#           --exclude='.mypy_cache' --exclude='.pytest_cache' --exclude='.venv' \
#           /workspace/ /mnt/workspace/
#     done
# ) &



exec "$@"