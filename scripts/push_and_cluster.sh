#!/usr/bin/env bash
# Run on the local computer: push code, update the cluster checkout, then
# optionally run a command on the cluster login node.

set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
REMOTE_HOST="${FERMIFLOW_REMOTE_HOST:?Set FERMIFLOW_REMOTE_HOST, e.g. whjing@your-login-host}"
REMOTE_REPO="${FERMIFLOW_REMOTE_REPO:-/share/home/whjing/gits_repo/fermiflow}"
BRANCH="${FERMIFLOW_BRANCH:-$(git -C "$ROOT_DIR" branch --show-current)}"

[[ -n "$BRANCH" ]] || { echo "Detached HEAD: choose a branch first." >&2; exit 2; }

cd "$ROOT_DIR"
git diff --check

if [[ -n "$(git status --porcelain)" ]]; then
    echo "Local changes are not committed. Commit them before synchronizing." >&2
    exit 2
fi

git push origin "HEAD:$BRANCH"

REMOTE_COMMAND="cd $(printf '%q' "$REMOTE_REPO") && FERMIFLOW_BRANCH=$(printf '%q' "$BRANCH") bash scripts/cluster_update.sh"

if (( $# > 0 )); then
    printf -v QUOTED_ARGS ' %q' "$@"
    REMOTE_COMMAND+=" &&$QUOTED_ARGS"
fi

ssh "$REMOTE_HOST" "$REMOTE_COMMAND"
