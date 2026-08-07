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

# Two checkout shapes, plus repo-alone. This repo used to sit at
# <ws>/addons/odoo with the venvs under <ws>/venv/ and the configs under
# <ws>/config/; it now sits at <ws>/odoo with the venv and the .conf directly
# under <ws>. Only the FIRST shape was recognised here, so in the current
# workspace `basename(dirname(ODOO_ROOT))` was "Odoo", not "addons", and this
# file declared a repo-alone checkout — `regen_model_types.sh` then died with
# "no workspace to discover a config from" in a workspace that had both a venv
# and a config all along.
#
# That is the same bug `_repo_root.py::_supplies_workspace_resources` documents
# as fixed ("Shape-matching is what broke") and that `tooling/_trampoline.sh`
# already handles. Of the three bootstraps in this repo, two got the fix and
# this one did not — exactly the drift `_trampoline.sh` was extracted to
# prevent. `tooling/test_repo_root.py` now asserts the three agree.
#
# A workspace is identified by what it SUPPLIES rather than by its shape (again
# mirroring `_repo_root.py`): an odoo `.conf` and/or a virtualenv. A CI
# checkout's parent (`/…/work/odoo`) supplies neither, so WORKSPACE stays empty
# there and the require_* functions say so — climbing blindly is how the
# doc-link gate ended up scanning a tree that wasn't there.
_supplies_workspace_resources() {
    local _dir="$1" _cand
    compgen -G "$_dir"/*.conf >/dev/null 2>&1 && return 0
    for _cand in "$_dir"/*/bin/python "$_dir"/venv/*/bin/python; do
        [[ -x "$_cand" ]] && return 0
    done
    return 1
}

if [[ "$(basename "$(dirname "$ODOO_ROOT")")" == "addons" ]]; then
    WORKSPACE="$(cd -- "$ODOO_ROOT/../.." && pwd)"
elif _supplies_workspace_resources "$(dirname "$ODOO_ROOT")"; then
    WORKSPACE="$(cd -- "$ODOO_ROOT/.." && pwd)"
else
    WORKSPACE=""
fi

# Resolve an interpreter into VENV_PY: a caller override, else the single venv
# in the workspace, else `python3` on PATH. That last fallback is the right
# answer for a stdlib-only generator in a repo-alone checkout, and is what
# .github/workflows/service_types.yml already uses when it calls the Python
# directly rather than through this wrapper.
#
# BOTH venv locations are searched, in the same order and with the same
# same-path guard as tooling/_trampoline.sh: <ws>/venv/<name>/bin/python is the
# historical layout, <ws>/<name>/bin/python is the current one. Searching only
# the first left VENV_PY empty here and silently fell through to /usr/bin/python3
# — which is a fine answer for the static service-types scan and a disastrous
# one for regen_model_types.sh, since odoo-bin under system Python cannot import
# the mandatory `odoo_rust` extension at all.
require_python() {
    if [[ -z "${VENV_PY:-}" && -n "$WORKSPACE" ]]; then
        local _cand
        for _cand in "$WORKSPACE"/venv/*/bin/python "$WORKSPACE"/*/bin/python; do
            [[ -x "$_cand" ]] || continue
            if [[ -n "${VENV_PY:-}" && "${VENV_PY}" != "$_cand" ]]; then
                echo "✗ several venvs under $WORKSPACE; set VENV_PY" >&2
                exit 2
            fi
            VENV_PY="$_cand"
        done
    fi
    if [[ -z "${VENV_PY:-}" ]]; then
        VENV_PY="$(command -v python3 || true)"
    fi
    if [[ -z "${VENV_PY:-}" || ! -x "$VENV_PY" ]]; then
        echo "✗ no usable python: no venv under ${WORKSPACE:-<none>} and no" \
             "python3 on PATH. Set VENV_PY=/path/to/python." >&2
        exit 2
    fi
}

# Resolve CONFIG, for wrappers that actually boot Odoo. Named after the venv,
# per this workspace's one-conf-per-environment convention. The conf sits
# directly at <ws>/<venv-name>.conf now and under <ws>/config/ historically; a
# lone <ws>/*.conf settles an unconventionally-named pair. All three are tried
# before giving up, because the failure mode of guessing only one is a wrapper
# that reports "no config" next to the config.
require_config() {
    require_python
    if [[ -z "${CONFIG:-}" ]]; then
        if [[ -z "$WORKSPACE" ]]; then
            echo "✗ repo-alone checkout: no workspace to discover a config from." >&2
            echo "  Set CONFIG=/path/to/odoo.conf." >&2
            exit 2
        fi
        local _venv_name _cand _only
        _venv_name="$(basename "$(dirname "$(dirname "$VENV_PY")")")"
        for _cand in "$WORKSPACE/${_venv_name}.conf" \
                     "$WORKSPACE/config/${_venv_name}.conf"; do
            [[ -f "$_cand" ]] && { CONFIG="$_cand"; break; }
        done
        if [[ -z "${CONFIG:-}" ]]; then
            _only=""
            for _cand in "$WORKSPACE"/*.conf; do
                [[ -f "$_cand" ]] || continue
                [[ -n "$_only" ]] && { _only=""; break; }
                _only="$_cand"
            done
            [[ -n "$_only" ]] && CONFIG="$_only"
        fi
    fi
    if [[ -z "${CONFIG:-}" || ! -f "$CONFIG" ]]; then
        echo "✗ Odoo config not found for venv '${VENV_PY}' under $WORKSPACE" >&2
        echo "  Tried <ws>/<venv>.conf, <ws>/config/<venv>.conf, and a lone <ws>/*.conf." >&2
        echo "  Set CONFIG=/path/to/odoo.conf" >&2
        exit 2
    fi
}
