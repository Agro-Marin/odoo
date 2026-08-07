# Self-locating sh/python trampoline, shared by the tooling/hoot/* runners.
#
# Sourced from inside the `''':' ... '''` polyglot preamble of an
# extension-less CLI script: it locates the checkout, picks the workspace venv
# interpreter, and re-execs the CALLING script with it, so no venv path is ever
# hardcoded. The checkout root is found by walking up for `odoo-bin` rather
# than counting directories, so moving a script cannot silently point it at the
# wrong tree. Override the interpreter with $ODOO_VENV_PYTHON when the
# workspace holds several venvs.
#
# This lived as 24 lines copy-pasted into three files. Two of the three were
# byte-identical and the third differed only in a comment — which is the state
# right before they drift, and the bootstrap is the worst place to discover a
# copy went stale. `$0` and `"$@"` survive a POSIX `.` unchanged, so the
# calling script is still the one re-exec'd.
#
# NB: no `set --` in here — it would clobber "$@" (the real CLI arguments).

here="$(cd "$(dirname "$0")" && pwd)"
root="$here"
while [ "$root" != "/" ] && [ ! -f "$root/odoo-bin" ]; do root="$(dirname "$root")"; done
if [ ! -f "$root/odoo-bin" ]; then
    echo "$(basename "$0"): no odoo-bin above $here; cannot locate the checkout" >&2
    exit 1
fi
# Two workspace layouts: the checkout used to sit at <ws>/addons/odoo with the
# venvs under <ws>/venv/, and now sits at <ws>/odoo with them directly under
# <ws>/. Derive <ws> from the checkout's own position rather than a fixed depth,
# and search both venv locations, so neither layout needs $ODOO_VENV_PYTHON.
if [ "$(basename "$(dirname "$root")")" = "addons" ]; then
    ws="$(cd "$root/../.." && pwd)"
else
    ws="$(cd "$root/.." && pwd)"
fi
py="${ODOO_VENV_PYTHON:-}"
if [ -z "$py" ]; then
    for cand in "$ws"/venv/*/bin/python "$ws"/*/bin/python; do
        [ -x "$cand" ] || continue
        if [ -n "$py" ] && [ "$py" != "$cand" ]; then
            echo "$(basename "$0"): several venvs under $ws; set ODOO_VENV_PYTHON" >&2
            exit 1
        fi
        py="$cand"
    done
    if [ -z "$py" ]; then
        echo "$(basename "$0"): no venv python under $ws or $ws/venv; set ODOO_VENV_PYTHON" >&2
        exit 1
    fi
fi
exec "$py" "$0" "$@"
