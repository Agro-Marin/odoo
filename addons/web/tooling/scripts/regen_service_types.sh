#!/bin/bash
# Convenience wrapper for tooling/scripts/generate_service_types.py.
#
# Unlike ``regen_model_types.sh``, this script does NOT need a running
# Odoo (services live in JS source, not the Python registry).  It is a
# pure static scan and runs in <1 second.  The wrapper exists for
# consistency with the model_types pattern, so operators have a single
# command to remember per generator.
#
# The Python script computes its own REPO_ROOT via
# ``Path(__file__).resolve().parents[6]``; this wrapper just locates
# the right interpreter and forwards arguments.
#
# USAGE
# -----
#   ./tooling/scripts/regen_service_types.sh                # regenerate
#   ./tooling/scripts/regen_service_types.sh --check        # CI gate mode
#   ./tooling/scripts/regen_service_types.sh --quiet        # no progress output
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname "$0")" && pwd)"
SCRIPT="${SCRIPT_DIR}/generate_service_types.py"

# Prefer the workspace venv (Python 3.14) when present so the wrapper
# matches the production interpreter.  Fall back to system python3 —
# the generator only uses stdlib (re, pathlib, dataclasses, argparse),
# so any 3.10+ interpreter works for both regen and --check.
VENV_PY="${VENV_PY:-${HOME}/Odoo/venv/agromarin/bin/python}"
if [[ ! -x "$VENV_PY" ]]; then
    VENV_PY="$(command -v python3)"
fi

exec "$VENV_PY" "$SCRIPT" "$@"
