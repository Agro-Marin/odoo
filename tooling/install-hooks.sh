#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if ! command -v pre-commit >/dev/null 2>&1; then
    echo "error: pre-commit is not on PATH. Install it first:" >&2
    echo "    pipx install pre-commit    # or: pip install pre-commit" >&2
    echo "then re-run tooling/install-hooks.sh" >&2
    exit 1
fi

pre-commit install
pre-commit install --hook-type commit-msg
pre-commit install --hook-type pre-push

echo
echo "Hooks installed for this clone: pre-commit, commit-msg,"
echo "pre-push (cross-repo symbol coherence, tooling/architecture/cross_repo_coherence.py)."
