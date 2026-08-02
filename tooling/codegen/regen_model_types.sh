#!/bin/bash
# Convenience wrapper for tooling/codegen/generate_model_types.py.
#
# Needs a running-capable Odoo: model types come from the Python registry via
# `odoo-bin shell`, not from static source. Feature requests belong in the
# Python script, not here.
#
# USAGE
# -----
#   ./tooling/codegen/regen_model_types.sh                     # all installed modules
#   ./tooling/codegen/regen_model_types.sh sale,sale_management
#   ./tooling/codegen/regen_model_types.sh --models=res.partner,res.users
#   DB=other_db ./tooling/codegen/regen_model_types.sh sale    # override DB
#
# VENV_PY / CONFIG / DB may be set to override the discovered defaults.
set -euo pipefail

# shellcheck source=./_resolve_env.sh
source "$(cd -- "$(dirname "$0")" && pwd)/_resolve_env.sh"

DB="${DB:-}"
SCRIPT="$(cd -- "$(dirname "$0")" && pwd)/generate_model_types.py"

if [[ ! -f "$CONFIG" ]]; then
    echo "✗ Odoo config not found at $CONFIG" >&2
    echo "  Set CONFIG=/path/to/odoo.conf" >&2
    exit 2
fi

if [[ -z "$DB" ]]; then
    echo "✗ no database given. Set DB=<dbname>." >&2
    exit 2
fi

# Select what to emit. The names travel in the ENVIRONMENT, never spliced into
# the Python below: the previous form built the call as a string
# (`modules=[... '${ARG}' ...]`) and interpolated it into an unquoted heredoc,
# so a single quote in an argument was a syntax error and anything else was
# arbitrary code in the odoo shell.
ARG="${1:-}"
case "$ARG" in
    --models=*) REGEN_KIND="models";  REGEN_NAMES="${ARG#--models=}" ;;
    "")         REGEN_KIND="all";     REGEN_NAMES="" ;;
    *)          REGEN_KIND="modules"; REGEN_NAMES="$ARG" ;;
esac
export REGEN_KIND REGEN_NAMES
REGEN_SCRIPT_DIR="$(dirname "$SCRIPT")"
export REGEN_SCRIPT_DIR

echo "▶ db=${DB} config=${CONFIG}"
echo "▶ ${REGEN_NAMES:+${REGEN_KIND}=${REGEN_NAMES}}${REGEN_NAMES:-(all installed modules)}"
echo

# odoo-bin shell binds ``env`` and reads stdin. ``--no-http`` + a
# non-default port avoid colliding with an already-running Odoo.
# Quoted heredoc delimiter: nothing here is shell-expanded.
"$VENV_PY" "${ODOO_ROOT}/odoo-bin" shell \
    -c "$CONFIG" -d "$DB" --no-http --http-port=8169 <<'PY'
import os
import sys

sys.path.insert(0, os.environ["REGEN_SCRIPT_DIR"])
from generate_model_types import generate

kind = os.environ["REGEN_KIND"]
names = [n.strip() for n in os.environ["REGEN_NAMES"].split(",") if n.strip()]
generate(env, **({} if kind == "all" else {kind: names}))
PY
