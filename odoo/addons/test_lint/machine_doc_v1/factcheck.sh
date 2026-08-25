#!/bin/bash
# test_lint machine-doc fact-check. Run from any cwd. Read-only.
#
# Assertions DERIVE their expected value from the tree and check that the docs
# agree, rather than keeping a second copy of every fact that can go stale
# independently. A doc that cites a checker, a rule or a gate that no longer
# exists is worse than no doc: it is read as current.
#
# The module carried no machine doc at all -- 9410 lines, 35 gates and no map --
# and the first run of this harness found a rule the map did not name.

set -u
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MOD="$(dirname "$SCRIPT_DIR")"                    # <repo>/odoo/addons/test_lint
REPO="$(cd "$MOD/../../.." && pwd)"
DOCS=("$SCRIPT_DIR"/*.md)

fail=0
pass=0
ok() { pass=$((pass + 1)); }
bad() {
    fail=$((fail + 1))
    printf '  FAIL  %s\n' "$1"
}

assert_doc_cites() { # <needle> <human description>
    if grep -qF -- "$1" "${DOCS[@]}"; then ok; else bad "docs never cite $2 ($1)"; fi
}
assert_file() { # <path> <human description>
    if [ -e "$1" ]; then ok; else bad "missing $2 ($1)"; fi
}

# Every checker module in the tree is named by the map.
for f in "$MOD"/tests/_checker_*.py; do
    assert_doc_cites "$(basename "$f")" "checker $(basename "$f")"
done

# Every rule the registry declares is named by the map.
rules="$(python3 "$SCRIPT_DIR/_rule_names.py" "$MOD/tests/_rules.py")"
if [ -z "$rules" ]; then
    bad "could not read any rule out of _rules.py"
fi
for rule in $rules; do
    assert_doc_cites "$rule" "rule $rule"
done

# The two halves, the fixers and their invariants.
assert_file "$MOD/tests/_rules.py" "the rule registry"
assert_file "$MOD/tests/_py_scan.py" "the scan engine"
assert_file "$MOD/tests/_xml_identity.py" "the document-identity module"
assert_file "$MOD/tests/_xml_sweep.py" "the shared fixer sweep"
assert_doc_cites "is_faithful" "the order-preserving invariant"
assert_doc_cites "preserves_content" "the order-insensitive invariant"

# The floors are in the ratchet, and at least one lint_* baseline exists there.
assert_file "$REPO/tooling/ratchet/ratchet.py" "the ratchet tool"
if ls "$REPO"/tooling/ratchet/baselines/lint_*.json >/dev/null 2>&1; then
    ok
else
    bad "no lint_* baseline in tooling/ratchet/baselines/"
fi

# No floor may live in Python any more: assert_ratchet must refuse an integer.
if grep -q "raise TypeError" "$MOD/tests/lint_case.py"; then
    ok
else
    bad "assert_ratchet no longer refuses a numeric floor"
fi

# Every backticked PATH in the docs resolves. `CLAUDE.md` holds machine docs to
# this: a deliberately-absent file is named in plain prose, never in backticks,
# so a backticked path that does not resolve is a doc citing something gone.
while read -r cited; do
    [ -n "$cited" ] || continue
    if [ -e "$REPO/$cited" ] || [ -e "$MOD/$cited" ] || [ -e "$MOD/tests/$cited" ]; then
        ok
    else
        bad "docs cite a path that does not resolve: $cited"
    fi
done < <(python3 "$SCRIPT_DIR/_cited_paths.py" "${DOCS[@]}")

# Both CI lanes the map names exist.
assert_file "$REPO/.github/workflows/test_lint.yml" "the test_lint lane"
assert_file "$REPO/.github/workflows/asset_lint.yml" "the asset_lint lane"

printf '\n%s: %d passed, %d failed\n' "$(basename "$MOD")" "$pass" "$fail"
[ "$fail" -eq 0 ]
