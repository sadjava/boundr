#!/usr/bin/env bash
# Run from any directory.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
if [[ ${1:-} == --help || ${1:-} == -h ]]; then
    printf 'Usage: bash run_all.sh [run-directory]\n'
    exit 0
fi
if (( $# > 1 )); then
    printf 'Usage: bash run_all.sh [run-directory]\n' >&2
    exit 2
fi
run_dir=$(realpath -m -- "${1:-runs/caption}")
mkdir -p -- "$run_dir"
exec 9>"$run_dir/run.lock"
flock -n 9 || { printf 'This run is already active.\n' >&2; exit 1; }
export PYTORCH_ALLOC_CONF=${PYTORCH_ALLOC_CONF:-expandable_segments:True}
trap 'run_exit_code=$?; printf "Workflow exited with status %s at %s\n" "$run_exit_code" "$(date -Is)"' EXIT

if [[ -e "$run_dir/adapter" ]]; then
    printf 'An adapter run already exists. Resume it with train.py --resume CHECKPOINT.\n' >&2
    exit 1
fi

.venv/bin/python data.py prepare --output "$run_dir/prepared"
.venv/bin/python -u cache.py --prepared "$run_dir/prepared" --output "$run_dir/cache"
.venv/bin/python -u train.py --cache "$run_dir/cache" --output "$run_dir/adapter"
