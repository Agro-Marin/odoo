#!/bin/bash
set -euo pipefail

source "$(cd -- "$(dirname "$0")" && pwd)/_resolve_env.sh"
require_config

DB="${DB:-}"
SCRIPT="$(cd -- "$(dirname "$0")" && pwd)/generate_model_types.py"

if [[ -z "$DB" ]]; then
    echo "✗ no database given. Set DB=<dbname>." >&2
    exit 2
fi

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
