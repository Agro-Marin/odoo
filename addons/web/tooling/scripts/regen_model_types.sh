#!/bin/bash
# Convenience wrapper for tooling/scripts/generate_model_types.py.
#
# Resolves the venv + Odoo config from the workspace conventions and
# invokes generate() over the supplied modules/models.  Inspired by the
# typecheck baseline workflow (`typecheck_gate.mjs`); intentionally
# minimal — feature requests should land in the Python script, not here.
#
# USAGE
# -----
#   ./tooling/scripts/regen_model_types.sh                     # all installed modules
#   ./tooling/scripts/regen_model_types.sh sale,sale_management
#   ./tooling/scripts/regen_model_types.sh --models=res.partner,res.users
#   DB=other_db ./tooling/scripts/regen_model_types.sh sale    # override DB
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname "$0")" && cd ../../../../.. && pwd)"
VENV_PY="${VENV_PY:-${REPO_ROOT}/venv/agromarin/bin/python}"
CONFIG="${CONFIG:-${REPO_ROOT}/conf/odoo.conf}"
DB="${DB:-marin190}"
SCRIPT="${REPO_ROOT}/addons/odoo/addons/web/tooling/scripts/generate_model_types.py"

if [[ ! -x "$VENV_PY" ]]; then
    echo "✗ Python venv not found at $VENV_PY" >&2
    echo "  Set VENV_PY=/path/to/python or follow setup-environment skill." >&2
    exit 2
fi

if [[ ! -f "$CONFIG" ]]; then
    echo "✗ Odoo config not found at $CONFIG" >&2
    echo "  Set CONFIG=/path/to/odoo.conf" >&2
    exit 2
fi

# Build the kwargs dict from the first positional or --models= flag.
ARG="${1:-}"
case "$ARG" in
    --models=*)
        MODELS_LIST="${ARG#--models=}"
        KWARGS="models=[m.strip() for m in '${MODELS_LIST}'.split(',')]"
        ;;
    "")
        KWARGS=""  # all installed modules
        ;;
    *)
        KWARGS="modules=[m.strip() for m in '${ARG}'.split(',')]"
        ;;
esac

echo "▶ db=${DB} config=${CONFIG}"
echo "▶ ${KWARGS:-(all installed modules)}"
echo

# odoo-bin shell binds ``env`` and reads stdin. ``--no-http`` + a
# non-default port avoid colliding with the running systemd Odoo.
"$VENV_PY" "${REPO_ROOT}/addons/odoo/odoo-bin" shell \
    -c "$CONFIG" -d "$DB" --no-http --http-port=8169 <<PY
import sys
sys.path.insert(0, '$(dirname "$SCRIPT")')
from generate_model_types import generate
generate(env, ${KWARGS})
PY
