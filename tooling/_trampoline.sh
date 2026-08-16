
# Sourced by the sh/python polyglots in tooling/ (hoot/hoot, hoot/hoot-shard,
# hoot/hoot-affected, bench/render_bench, bench/discuss_bench). Each opens with
#
#     #!/bin/sh
#     ''':'
#     … these lines …
#     '''
#
# which sh reads as '' + ':' — the no-op `:` builtin, so the shell falls through
# to the code below and re-execs the file under the venv interpreter — while
# python reads the same span as a triple-quoted string and skips it.
#
# Those two delimiters are why every caller wraps them in `# fmt: off` /
# `# fmt: on`. `ruff format` normalises quotes to double and would rewrite ''' to
# """: identical Python, but sh reads """ as '' followed by an unterminated ",
# swallowing the trampoline into a string and killing the runner with
# `Syntax error: word unexpected`. `ruff check` cannot catch it — the Python half
# stays valid — and .pre-commit-config.yaml runs ruff-format on staged files, so
# without the guard a one-line edit to any of these files breaks it on commit.
# Do not remove the fmt pragmas, and do not "fix" the quotes.

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
