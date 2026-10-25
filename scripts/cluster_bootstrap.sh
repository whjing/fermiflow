#!/usr/bin/env bash
# Run once on the cluster after cloning fermiflow.

set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
CONDA_SH="${CONDA_SH:-/share/home/whjing/miniforge3/etc/profile.d/conda.sh}"
CONDA_ENV="${CONDA_ENV:-fermi}"

[[ -f "$CONDA_SH" ]] || { echo "conda.sh not found: $CONDA_SH" >&2; exit 1; }

source "$CONDA_SH"
conda activate "$CONDA_ENV"
python -m pip install -e "$ROOT_DIR" --no-deps

echo "Installed editable fermiflow from: $ROOT_DIR"
fermiflow path
