#!/bin/bash
# Fact-check for addons/web/doc/. Run from any cwd. Read-only. CI-safe.
# Covers COMPONENT_DIAGRAM.md, FLOW_DIAGRAM.md, LAZY_VIEW_LOADING.md.
#
# Assertions DERIVE their expected value from the filesystem and check the docs
# agree, rather than keeping a second copy of every number.
#
# Sibling of machine_doc_v1/factcheck.sh, which scopes itself to that directory.

set -u
WEB="/home/marin/Odoo/addons/odoo/addons/web"
DOC="$WEB/doc"
ODOO="/home/marin/Odoo/addons/odoo"
PASS=0
FAIL=0

ok()   { echo "PASS: $1"; PASS=$((PASS+1)); }
bad()  { echo "FAIL: $1"; FAIL=$((FAIL+1)); }

assert_eq() {
    local name="$1" actual="$2" expected="$3"
    if [ "$actual" = "$expected" ]; then ok "$name [$actual]"
    else bad "$name — expected [$expected] got [$actual]"; fi
}

# Claims of absence rot silently: the doc says "there is no X", someone adds an
# X, nothing notices.
assert_absent() {
    local name="$1" pat="$2" path="$3"
    local hits
    hits=$(grep -rEl "$pat" "$path" 2>/dev/null | grep -v '/doc/' | head -5)
    if [ -z "$hits" ]; then ok "$name (absent)"
    else bad "$name — expected no match for /$pat/, found: $(echo "$hits" | tr '\n' ' ')"; fi
}

assert_grep() {
    local name="$1" pat="$2" file="$3"
    if grep -qE "$pat" "$file" 2>/dev/null; then ok "$name"
    else bad "$name — /$pat/ not found in ${file#$ODOO/}"; fi
}

echo "=== 1. Every repo path cited in the docs exists ==="
# Backticked tokens that look like repo-relative source paths.
grep -ohE '`(static/src|controllers|models|views)/[A-Za-z0-9_./-]+`' "$DOC"/*.md \
    | tr -d '`' | sed 's:/$::' | sort -u | while read -r p; do
    # Area 10 lists relational_model files relative to static/src/model/.
    if [ -e "$WEB/$p" ] || [ -e "$WEB/static/src/model/$p" ]; then
        :
    else
        echo "FAIL: cited path does not exist: $p"
    fi
done > /tmp/.doc_paths.$$ 2>/dev/null
if [ -s /tmp/.doc_paths.$$ ]; then
    cat /tmp/.doc_paths.$$; FAIL=$((FAIL+$(wc -l < /tmp/.doc_paths.$$)))
else
    ok "all cited source paths resolve"
fi
rm -f /tmp/.doc_paths.$$

echo
echo "=== 2. Line-count table rows match wc -l ==="
# Rows shaped: | JS | `path` | 123 | role |
n_rows=0; n_bad=0
while IFS= read -r line; do
    p=$(echo "$line" | sed -E 's/^\| *[A-Za-z]+ *\| *`([^`]+)`.*/\1/')
    claimed=$(echo "$line" | sed -E 's/^\| *[A-Za-z]+ *\| *`[^`]+` *\| *([0-9]+) *\|.*/\1/')
    f=""
    [ -f "$WEB/$p" ] && f="$WEB/$p"
    [ -z "$f" ] && [ -f "$WEB/static/src/model/$p" ] && f="$WEB/static/src/model/$p"
    [ -z "$f" ] && continue
    n_rows=$((n_rows+1))
    real=$(wc -l < "$f")
    if [ "$real" != "$claimed" ]; then
        echo "FAIL: line count $p — doc says $claimed, wc -l says $real"
        n_bad=$((n_bad+1))
    fi
done < <(grep -hE '^\| *[A-Za-z]+ *\| *`[^`]+` *\| *[0-9]+ *\|' "$DOC"/*.md)
if [ "$n_bad" -eq 0 ]; then ok "all $n_rows line-count rows match"
else FAIL=$((FAIL+n_bad)); fi

echo
echo "=== 3. Directory file-count rows match find -type f ==="
n_bad=0; n_rows=0
while IFS= read -r line; do
    p=$(echo "$line" | sed -E 's/^\| *[A-Za-z]+ *\| *`([^`]+)`.*/\1/')
    claimed=$(echo "$line" | sed -E 's/^\| *[A-Za-z]+ *\| *`[^`]+` *\| *([0-9]+).*/\1/')
    [ -d "$WEB/$p" ] || continue
    n_rows=$((n_rows+1))
    real=$(find "$WEB/$p" -type f | wc -l)
    if [ "$real" != "$claimed" ]; then
        echo "FAIL: file count $p — doc says $claimed, find says $real"
        n_bad=$((n_bad+1))
    fi
done < <(grep -hE '^\| *[A-Za-z]+ *\| *`[^`]+/` *\| *[0-9]+ *(files?|\()' "$DOC"/*.md)
if [ "$n_bad" -eq 0 ]; then ok "all $n_rows directory-count rows match"
else FAIL=$((FAIL+n_bad)); fi

echo
echo "=== 4. Claims of absence ==="
# COMPONENT_DIAGRAM Area 1 / FLOW_DIAGRAM Flow 1.
assert_absent "session.js does not delete __session_info__" \
    'delete +(odoo|globalThis\.odoo)\.__session_info__' "$WEB/static/src"
# FLOW_DIAGRAM Flow 10: no lazy backend bundle.
assert_absent "no web.assets_backend_lazy bundle is declared" \
    '"web\.assets_backend_lazy"' "$WEB/__manifest__.py"
# LAZY_VIEW_LOADING: mechanism reverted, must stay out of the tree.
assert_absent "lazy view registry is not in the tree" \
    'lazyViewRegistry|lazy_views' "$WEB/static/src"
# COMPONENT_DIAGRAM Area 6: zero core-web registrations.
assert_absent "action_handlers has no core-web registrations" \
    'category\("action_handlers"\)\.add' "$WEB/static/src"
# COMPONENT_DIAGRAM Area 7: list has no compiler.
if [ -z "$(find "$WEB/static/src/views/list" -name '*compiler*' 2>/dev/null)" ]; then
    ok "list view has no compiler (deliberate divergence)"
else
    bad "list view gained a compiler — Area 7's 'compiler asymmetry' note is stale"
fi

echo
echo "=== 5. Constants and structure the docs quote verbatim ==="
assert_eq "MAX_ACTION_DEPTH" \
    "$(grep -oE 'MAX_ACTION_DEPTH *= *[0-9]+' "$WEB/static/src/webclient/actions/action_constants.js" | grep -oE '[0-9]+')" \
    "20"
assert_eq "RESULT_SET_REMOVING_METHODS size" \
    "$(sed -n '/RESULT_SET_REMOVING_METHODS = new Set(\[/,/\]/p' "$WEB/static/src/services/result_set_cache_invalidator_service.js" | grep -cE '^\s*"')" \
    "3"
assert_eq "form_compiler.js registers 10 selectors of its own" \
    "$(sed -n '/compilers.push(/,/^        );/p' "$WEB/static/src/views/form/form_compiler.js" | grep -c 'selector:')" \
    "10"
assert_eq "kanban ACTION_TYPES" \
    "$(grep -oE 'ACTION_TYPES = \[[^]]*\]' "$WEB/static/src/views/kanban/kanban_compiler.js")" \
    'ACTION_TYPES = ["action", "object"]'
# Area 3 security note rests on this gate.
assert_grep "serialize_exception gates debug on dev_mode" \
    '_hide_exception_internals' "$ODOO/odoo/http/helpers.py"
assert_grep "_hide_exception_internals reads config\[\"dev_mode\"\]" \
    'config\["dev_mode"\]' "$ODOO/odoo/http/helpers.py"
# Area 11 / Flow 9.
assert_grep "/web/filestore raises not_found" \
    'not_found\(\)' "$WEB/controllers/binary.py"
# Flow 12.
assert_grep "constructDateRange uses inclusive bounds" \
    '">=", leftBound' "$WEB/static/src/search/utils/dates.js"
# Flow 13 / session.py.
assert_grep "/web/session/logout defaults to /odoo" \
    'def logout\(self, redirect: str = "/odoo"\)' "$WEB/controllers/session.py"

echo
echo "=== 6. Versions the docs pin ==="
if [ -x "$ODOO/node_modules/esbuild/bin/esbuild" ]; then
    v=$("$ODOO/node_modules/esbuild/bin/esbuild" --version 2>/dev/null)
    if grep -qF "$v" "$DOC/LAZY_VIEW_LOADING.md"; then
        ok "LAZY_VIEW_LOADING.md cites the installed esbuild [$v]"
    else
        bad "esbuild is $v but LAZY_VIEW_LOADING.md does not cite it"
    fi
else
    echo "SKIP: esbuild binary not present"
fi

echo
echo "======================================"
echo "PASS: $PASS   FAIL: $FAIL"
[ "$FAIL" -eq 0 ] || exit 1
