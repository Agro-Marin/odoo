#!/bin/bash
set -euo pipefail

source "$(cd -- "$(dirname "$0")" && pwd)/_resolve_env.sh"
require_python

SCRIPT="$(cd -- "$(dirname "$0")" && pwd)/generate_service_types.py"

exec "$VENV_PY" "$SCRIPT" "$@"
