#!/usr/bin/env bash
# Download one URL per line with several independent wget workers.
#
# Usage:
#   bash scripts/download.sh urls.txt rawdata 6
#   fermiflow download urls.txt rawdata 6

set -euo pipefail

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    echo "Usage: bash scripts/download.sh URLS.txt [OUTPUT_DIR] [JOBS]"
    echo "Download one wget URL per line with parallel workers."
    exit 0
fi

URL_FILE="${1:?Usage: download.sh URLS.txt [OUTPUT_DIR] [JOBS]}"
OUTPUT_DIR="${2:-rawdata}"
JOBS="${3:-4}"

[[ -f "$URL_FILE" ]] || { echo "URL list not found: $URL_FILE" >&2; exit 1; }
[[ "$JOBS" =~ ^[1-9][0-9]*$ ]] || { echo "JOBS must be a positive integer." >&2; exit 1; }

mkdir -p "$OUTPUT_DIR"

# The list may contain one URL per line, or ordinary ``wget ... URL`` lines
# copied from a download page or an old shell script.  Extract every HTTP(S)
# URL and ignore blank lines, comments, and other text.
mapfile -t URLS < <(grep -Eo 'https?://[^[:space:]]+' "$URL_FILE" | awk '!seen[$0]++' || true)

(( ${#URLS[@]} > 0 )) || { echo "No URLs found in: $URL_FILE" >&2; exit 1; }

printf '%s\n' "${URLS[@]}" | xargs -r -n 1 -P "$JOBS" \
    wget --continue --directory-prefix="$OUTPUT_DIR" --no-verbose

echo "Downloaded ${#URLS[@]} URL(s) into: $OUTPUT_DIR"
