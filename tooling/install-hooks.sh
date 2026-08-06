#!/usr/bin/env bash
# Install this clone's git hooks. Run once per clone, from anywhere:
#
#     tooling/install-hooks.sh
#
# `.pre-commit-config.yaml` DECLARES hooks; it installs nothing. Each clone
# must run `pre-commit install` for each hook stage, or the declarations are
# dead text — a 2026-08 audit found exactly that: the pre-push
# cross_repo_coherence gate was declared, and no clone in the workspace had
# any hook installed (`.git/hooks` held only samples). This script is the one
# command that makes the declarations real, so the gap cannot reopen quietly.
#
# The pre-push stage matters most here: it runs
# tooling/architecture/cross_repo_coherence.py --check, which stops a push
# that removes a JS module a sibling checkout still imports (the t23778
# incident). CI cannot replace it — the sibling repos' architecture workflows
# re-check the boundary post-hoc, but only this hook stops the push itself.
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
