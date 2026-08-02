# Shared venv/config discovery for the codegen wrappers. Source, don't execute.
#
# Mirrors the trampoline in tooling/hoot/hoot: pick the single venv
# under <workspace>/venv and pair it with config/<venv-name>.conf. Nothing is
# hardcoded — the previous wrappers pinned a named venv and `conf/odoo.conf`,
# neither of which exists in this workspace, so both were dead on arrival and
# failed only at the point of use.
#
# Sets: ODOO_ROOT, WORKSPACE, VENV_PY, CONFIG (each honouring a caller override).

_here="$(cd -- "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

ODOO_ROOT="$_here"
while [[ "$ODOO_ROOT" != "/" && ! -f "$ODOO_ROOT/odoo-bin" ]]; do
    ODOO_ROOT="$(dirname "$ODOO_ROOT")"
done
if [[ ! -f "$ODOO_ROOT/odoo-bin" ]]; then
    echo "✗ no odoo-bin above $_here — cannot locate the odoo checkout root" >&2
    exit 2
fi

# The workspace only exists when this repo is checked out as <ws>/addons/odoo.
# In a repo-alone checkout there is nothing above it to discover, so require the
# caller to say — climbing blindly is how the doc-link gate ended up scanning a
# tree that wasn't there.
if [[ "$(basename "$(dirname "$ODOO_ROOT")")" == "addons" ]]; then
    WORKSPACE="$(cd -- "$ODOO_ROOT/../.." && pwd)"
elif [[ -n "${VENV_PY:-}" && -n "${CONFIG:-}" ]]; then
    WORKSPACE=""
else
    echo "✗ repo-alone checkout: no workspace to discover a venv/config from." >&2
    echo "  Set both VENV_PY=/path/to/python and CONFIG=/path/to/odoo.conf." >&2
    exit 2
fi

if [[ -z "${VENV_PY:-}" ]]; then
    for _cand in "$WORKSPACE"/venv/*/bin/python; do
        [[ -x "$_cand" ]] || continue
        if [[ -n "${VENV_PY:-}" ]]; then
            echo "✗ several venvs under $WORKSPACE/venv; set VENV_PY" >&2
            exit 2
        fi
        VENV_PY="$_cand"
    done
fi
if [[ -z "${VENV_PY:-}" || ! -x "$VENV_PY" ]]; then
    echo "✗ no venv python under $WORKSPACE/venv; set VENV_PY=/path/to/python" >&2
    exit 2
fi

if [[ -z "${CONFIG:-}" ]]; then
    _venv_name="$(basename "$(dirname "$(dirname "$VENV_PY")")")"
    CONFIG="$WORKSPACE/config/${_venv_name}.conf"
fi
