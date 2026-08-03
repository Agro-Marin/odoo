# Shared environment discovery for the codegen wrappers. Source, don't execute.
#
# Mirrors the trampoline in tooling/hoot/hoot: locate the checkout by walking up
# for `odoo-bin`, then pick the single venv under <workspace>/venv and pair it
# with config/<venv-name>.conf. Nothing is hardcoded — the previous wrappers
# pinned a named venv and `conf/odoo.conf`, neither of which exists in this
# workspace, so both were dead on arrival and failed only at the point of use.
#
# Sourcing this resolves ODOO_ROOT and WORKSPACE and defines two functions:
#
#   require_python   ...plus a usable interpreter. Enough for a static scan.
#   require_config   ...plus CONFIG. Only for wrappers that boot Odoo.
#
# Discovery deliberately does NOT fail at source time any more. The two wrappers
# need different things, and a shared prologue demanding the union of both is
# why the SERVICE generator — a pure static scan of JS source, no database, no
# config — exited 2 in a repo-alone checkout asking for a CONFIG it never reads.
# That is the layout CI uses, and `./tooling/codegen/regen_service_types.sh` is
# the exact command service_types.yml prints when the gate fails.
#
# VENV_PY / CONFIG may be preset by the caller to override discovery.

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
# In a repo-alone checkout there is nothing above it to discover, so it stays
# empty and the require_* functions say so — climbing blindly is how the
# doc-link gate ended up scanning a tree that wasn't there.
if [[ "$(basename "$(dirname "$ODOO_ROOT")")" == "addons" ]]; then
    WORKSPACE="$(cd -- "$ODOO_ROOT/../.." && pwd)"
else
    WORKSPACE=""
fi

# Resolve an interpreter into VENV_PY: a caller override, else the single venv
# under <ws>/venv, else `python3` on PATH. That last fallback is the right
# answer for a stdlib-only generator in a repo-alone checkout, and is what
# .github/workflows/service_types.yml already uses when it calls the Python
# directly rather than through this wrapper.
require_python() {
    if [[ -z "${VENV_PY:-}" && -n "$WORKSPACE" ]]; then
        local _cand
        for _cand in "$WORKSPACE"/venv/*/bin/python; do
            [[ -x "$_cand" ]] || continue
            if [[ -n "${VENV_PY:-}" ]]; then
                echo "✗ several venvs under $WORKSPACE/venv; set VENV_PY" >&2
                exit 2
            fi
            VENV_PY="$_cand"
        done
    fi
    if [[ -z "${VENV_PY:-}" ]]; then
        VENV_PY="$(command -v python3 || true)"
    fi
    if [[ -z "${VENV_PY:-}" || ! -x "$VENV_PY" ]]; then
        echo "✗ no usable python: no venv under ${WORKSPACE:-<none>}/venv and no" \
             "python3 on PATH. Set VENV_PY=/path/to/python." >&2
        exit 2
    fi
}

# Resolve CONFIG, for wrappers that actually boot Odoo. Named after the venv,
# per this workspace's one-conf-per-environment convention.
require_config() {
    require_python
    if [[ -z "${CONFIG:-}" ]]; then
        if [[ -z "$WORKSPACE" ]]; then
            echo "✗ repo-alone checkout: no workspace to discover a config from." >&2
            echo "  Set CONFIG=/path/to/odoo.conf." >&2
            exit 2
        fi
        local _venv_name
        _venv_name="$(basename "$(dirname "$(dirname "$VENV_PY")")")"
        CONFIG="$WORKSPACE/config/${_venv_name}.conf"
    fi
    if [[ ! -f "$CONFIG" ]]; then
        echo "✗ Odoo config not found at $CONFIG" >&2
        echo "  Set CONFIG=/path/to/odoo.conf" >&2
        exit 2
    fi
}
