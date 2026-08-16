
_here="$(cd -- "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

ODOO_ROOT="$_here"
while [[ "$ODOO_ROOT" != "/" && ! -f "$ODOO_ROOT/odoo-bin" ]]; do
    ODOO_ROOT="$(dirname "$ODOO_ROOT")"
done
if [[ ! -f "$ODOO_ROOT/odoo-bin" ]]; then
    echo "✗ no odoo-bin above $_here — cannot locate the odoo checkout root" >&2
    exit 2
fi

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
