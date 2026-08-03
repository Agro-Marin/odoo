#!/bin/bash
# Convenience wrapper for tooling/codegen/generate_service_types.py.
#
# Unlike ``regen_model_types.sh``, this script does NOT need a running
# Odoo (services live in JS source, not the Python registry).  It is a
# pure static scan and runs in <1 second.  The wrapper exists for
# consistency with the model_types pattern, so operators have a single
# command to remember per generator.
#
# USAGE
# -----
#   ./tooling/codegen/regen_service_types.sh                # regenerate
#   ./tooling/codegen/regen_service_types.sh --check        # CI gate mode
#   ./tooling/codegen/regen_service_types.sh --quiet        # no progress output
set -euo pipefail

# shellcheck source=./_resolve_env.sh
source "$(cd -- "$(dirname "$0")" && pwd)/_resolve_env.sh"
# An interpreter and nothing else: no database, no config. Asking for a CONFIG
# here made this wrapper unusable in exactly the checkout shape CI uses.
require_python

SCRIPT="$(cd -- "$(dirname "$0")" && pwd)/generate_service_types.py"

exec "$VENV_PY" "$SCRIPT" "$@"
