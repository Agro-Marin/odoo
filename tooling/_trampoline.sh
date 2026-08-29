here="$(cd "$(dirname "$0")" && pwd)"
root="$here"
while [ "$root" != "/" ] && [ ! -f "$root/odoo-bin" ]; do root="$(dirname "$root")"; done
if [ ! -f "$root/odoo-bin" ]; then
    echo "$(basename "$0"): no odoo-bin above $here; cannot locate the checkout" >&2
    exit 1
fi
if [ "$(basename "$(dirname "$root")")" = "addons" ]; then
    ws="$(cd "$root/../.." && pwd)"
else
    ws="$(cd "$root/.." && pwd)"
fi
py="${ODOO_VENV_PYTHON:-}"
if [ -z "$py" ] && [ -n "${ODOO_CONF:-}" ]; then
    # hoot_lib._find_conf picks <venv name>.conf; this is that rule inverted.
    # A workspace holding one .conf per environment, each beside its own venv,
    # is the documented shape -- and it used to make every runner here refuse.
    env_name="$(basename "${ODOO_CONF}")"
    env_name="${env_name%.conf}"
    for cand in "$ws/$env_name/bin/python" "$ws/venv/$env_name/bin/python"; do
        [ -x "$cand" ] || continue
        py="$cand"
        break
    done
    if [ -z "$py" ]; then
        echo "$(basename "$0"): \$ODOO_CONF names $env_name, and neither" >&2
        echo "  $ws/$env_name/bin/python nor $ws/venv/$env_name/bin/python exists" >&2
        exit 1
    fi
fi
if [ -z "$py" ]; then
    found=""
    for cand in "$ws"/venv/*/bin/python "$ws"/*/bin/python; do
        [ -x "$cand" ] || continue
        case " $found " in *" $cand "*) continue ;; esac
        found="$found $cand"
    done
    # Count without `set --`: it assigns the positional parameters, and the exec
    # below forwards "$@" to the runner. `set -- $found` therefore replaced every
    # argument the caller typed with the candidate list, so with one venv found
    # `hoot --db mine '@web/x'` reached the python half as `hoot <interpreter>`.
    n=0
    for cand in $found; do
        n=$((n + 1))
        [ "$n" -eq 1 ] && py="$cand"
    done
    if [ "$n" -eq 0 ]; then
        echo "$(basename "$0"): no venv python under $ws or $ws/venv;" >&2
        echo "  set ODOO_VENV_PYTHON, or ODOO_CONF to name the environment" >&2
        exit 1
    elif [ "$n" -gt 1 ]; then
        echo "$(basename "$0"): $n venvs under $ws and no way to choose:" >&2
        for cand in $found; do echo "    $cand" >&2; done
        echo "  set ODOO_CONF to the environment's config, or ODOO_VENV_PYTHON" >&2
        echo "  to the interpreter itself" >&2
        exit 1
    fi
fi
exec "$py" "$0" "$@"
