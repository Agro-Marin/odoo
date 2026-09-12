# Interpreter resolution for the machine_doc factcheck harnesses.
#
# Source this, then use "$PY" and py_capture instead of calling python3.
#
# These harnesses read the tree with `ast.parse`, so the interpreter running
# them has to be able to parse the source this repo actually contains. Bare
# `python3` is whatever the host ships, and on a host whose system Python is
# older than the repo floor every scan raises SyntaxError -- Python 3.14 accepts
# `except A, B:` without parentheses (PEP 758), and the mail controllers use it.
#
# That failure did not look like a failure. A scan runs inside `$(...)`, so the
# traceback went to stderr, the substitution yielded an empty string, and the
# assertion reported a mismatch against an empty measurement: "expected [<sha>]
# got []". Read as a stale pin rather than a dead scanner, the documented repair
# is to re-pin the digest -- which would have compared the empty string to
# itself forever after. 58 of 68 failures across four harnesses were this, and
# they were hiding 9 real ones.
#
# So both halves are enforced here: the interpreter must satisfy the repo's own
# floor, and a scan that exits non-zero aborts the harness instead of returning
# a value.

_factcheck_here="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
FACTCHECK_ROOT="$_factcheck_here"
while [[ "$FACTCHECK_ROOT" != "/" && ! -f "$FACTCHECK_ROOT/odoo-bin" ]]; do
    FACTCHECK_ROOT="$(dirname -- "$FACTCHECK_ROOT")"
done
if [[ ! -f "$FACTCHECK_ROOT/odoo-bin" ]]; then
    echo "✗ factcheck_env.sh: no odoo-bin above $_factcheck_here" >&2
    exit 2
fi

# The floor is read from release.py rather than restated, so it cannot drift
# from the one odoo/init.py enforces at import.
_factcheck_floor="$(sed -n 's/^MIN_PY_VERSION.*(\([0-9]*\), *\([0-9]*\)).*/\1.\2/p' \
    "$FACTCHECK_ROOT/odoo/release.py")"
if [[ -z "$_factcheck_floor" ]]; then
    echo "✗ factcheck_env.sh: cannot read MIN_PY_VERSION from odoo/release.py" >&2
    exit 2
fi

# An
# explicit interpreter wins, then the single venv beside the checkout.
if [[ "$(basename -- "$(dirname -- "$FACTCHECK_ROOT")")" == "addons" ]]; then
    _factcheck_ws="$(cd -- "$FACTCHECK_ROOT/../.." && pwd)"
else
    _factcheck_ws="$(cd -- "$FACTCHECK_ROOT/.." && pwd)"
fi
PY="${VENV_PY:-${ODOO_VENV_PYTHON:-}}"
if [[ -z "$PY" ]]; then
    for _cand in "$_factcheck_ws"/venv/*/bin/python "$_factcheck_ws"/*/bin/python; do
        [[ -x "$_cand" ]] || continue
        if [[ -n "$PY" && "$PY" != "$_cand" ]]; then
            echo "✗ factcheck_env.sh: several venvs under $_factcheck_ws;" \
                 "set ODOO_VENV_PYTHON" >&2
            exit 2
        fi
        PY="$_cand"
    done
fi
[[ -n "$PY" ]] || PY="$(command -v python3 || true)"

# Checked, never assumed: falling back to a too-old interpreter is exactly the
# state this file exists to make impossible, so it is refused rather than used.
if [[ -z "$PY" ]] || ! "$PY" -c "
import sys
floor = tuple(int(p) for p in '$_factcheck_floor'.split('.'))
sys.exit(0 if sys.version_info[:len(floor)] >= floor else 1)
" 2>/dev/null; then
    echo "✗ factcheck_env.sh: need Python >= $_factcheck_floor to parse this" \
         "tree, got ${PY:-<none>} ($("${PY:-false}" -V 2>&1 || echo 'not runnable'))" >&2
    echo "  Set ODOO_VENV_PYTHON to the checkout's interpreter." >&2
    exit 2
fi
export PY

# Run a scan and abort if it fails. `x=$(py_capture <<'EOF' ... )` cannot leave
# `x` empty because the interpreter died: that is the whole point.
py_capture() {
    local _out _rc
    _out="$("$PY" "$@")"
    _rc=$?
    if [[ $_rc -ne 0 ]]; then
        echo "✗ factcheck: scan exited $_rc under $PY -- measurement abandoned" >&2
        exit 2
    fi
    printf '%s' "$_out"
}
