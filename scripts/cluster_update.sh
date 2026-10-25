#!/usr/bin/env bash
# Update this checkout safely before submitting work from the cluster login node.

set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
BRANCH="${FERMIFLOW_BRANCH:-main}"

cd "$ROOT_DIR"

if [[ -n "$(git status --porcelain)" ]]; then
    echo "Refusing to update: the cluster checkout has uncommitted changes." >&2
    echo "Commit, stash, or discard them intentionally; do not overwrite them automatically." >&2
    exit 2
fi

git fetch origin "$BRANCH"
git switch "$BRANCH"
git pull --ff-only origin "$BRANCH"

echo "fermiflow updated to $(git rev-parse --short HEAD) on branch $BRANCH"
