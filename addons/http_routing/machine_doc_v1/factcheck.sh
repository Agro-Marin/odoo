#!/bin/bash
# http_routing machine-doc fact-check. Run from any cwd. Read-only.
#
# Assertions DERIVE their expected value from the source tree and check that the
# docs agree, rather than keeping a second copy of every fact that can go stale
# independently. A doc that cites a method, a template or a test class which no
# longer exists is worse than no doc: it is read as current.
#
# Roots come from this script's own location, so the run always validates the
# tree it ships in.

set -u
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MOD="$(dirname "$SCRIPT_DIR")"                  # <repo>/addons/http_routing
DOCS=("$SCRIPT_DIR"/*.md)

fail=0
pass=0
skip=0

ok()   { pass=$((pass + 1)); }
bad()  { fail=$((fail + 1)); printf '  FAIL  %s\n' "$1"; }
note() { skip=$((skip + 1)); printf '  SKIP  %s\n' "$1"; }

# Assert every doc mentioning a name uses one that exists in the source.
assert_doc_cites() {  # <needle> <human description>
    if grep -qF -- "$1" "${DOCS[@]}"; then ok; else bad "docs never cite $2 ($1)"; fi
}

printf '== http_routing machine_doc_v1 factcheck ==\n'

# ---------------------------------------------------------------- structure --
for f in ARCHITECTURE.md TRAPS.md TEST_MAP.md; do
    [ -f "$SCRIPT_DIR/$f" ] && ok || bad "missing $f"
done

# ------------------------------------------------------------------- routes --
# Every @http.route path in the controllers must be named by the docs. The
# translations route is declared through a constant, so accept either spelling.
route_const=$(grep -oP 'FRONTEND_TRANSLATIONS_ROUTE\s*=\s*"\K[^"]+' \
    "$MOD/models/ir_http.py" 2>/dev/null)
if [ -n "$route_const" ]; then
    assert_doc_cites "$route_const" "the frontend translations route"
else
    bad "FRONTEND_TRANSLATIONS_ROUTE is gone from models/ir_http.py"
fi
while read -r route; do
    [ -z "$route" ] && continue
    assert_doc_cites "$route" "route $route"
done < <(grep -oP '@http\.route\(\s*"\K[^"]+' "$MOD/controllers/main.py")

# --------------------------------------------------------------- primitives --
# The URL-grammar primitives the docs promise everything routes through.
for meth in _url_split_suffix _lang_url_prefix _lang_url_split _frontend_url_codes \
            _url_lang _url_localized _is_multilang_url url_rewrite \
            _reroute_for_lang _redirect_lang _get_error_template; do
    if grep -q "def $meth" "$MOD/models/ir_http.py"; then
        assert_doc_cites "$meth" "$meth"
    else
        bad "$meth no longer exists in models/ir_http.py"
    fi
done

# ---------------------------------------------------------------- templates --
# Every error template shipped must be documented, and vice versa.
while read -r tpl; do
    [ -z "$tpl" ] && continue
    assert_doc_cites "http_routing.$tpl" "template http_routing.$tpl"
done < <(grep -oP 'template id="\K[^"]+' "$MOD/views/http_routing_template.xml")

# ------------------------------------------------------------ test coverage --
# TEST_MAP must list every test class, and must not list one that is gone.
mapfile -t classes < <(grep -hoP '^class \K(Test\w+)' "$MOD"/tests/test_*.py | sort -u)
for cls in "${classes[@]}"; do
    if grep -qF "$cls" "$SCRIPT_DIR/TEST_MAP.md"; then ok
    else bad "TEST_MAP.md does not list test class $cls"; fi
done
while read -r cited; do
    [ -z "$cited" ] && continue
    if printf '%s\n' "${classes[@]}" | grep -qx "$cited"; then ok
    else bad "docs cite test class $cited, which no longer exists"; fi
done < <(grep -hoP '\bTest[A-Z]\w+' "${DOCS[@]}" | sort -u)

# ------------------------------------------------------- ladder cases exist --
# The docs describe cases /2../9; _match's docstring is their source.
for case_no in 2 3 4 5 6 7 8 9; do
    if grep -q "See /$case_no," "$MOD/models/ir_http.py"; then ok
    else bad "ladder case /$case_no is no longer marked in models/ir_http.py"; fi
done

# ------------------------------------------- claims that must stay verified --
# TRAPS §3: the converter rejects a falsy id. TRAPS §4: MissingError/AccessError
# must NOT be swallowed by the canonical-slug guard.
grep -q "raise werkzeug.routing.ValidationError" "$MOD/models/ir_http.py" \
    && ok || bad "TRAPS.md §3 claims the converter rejects id 0; it no longer does"
if grep -q "except (ValueError, TypeError, werkzeug.routing.ValidationError)" \
        "$MOD/models/ir_http.py"; then ok
else bad "TRAPS.md §4 claims MissingError/AccessError escape the slug guard; the except clause changed"; fi

# _REDIRECTABLE_METHODS must stay GET/HEAD only (TRAPS/ARCHITECTURE both say so)
if grep -q '_REDIRECTABLE_METHODS = ("GET", "HEAD")' "$MOD/models/ir_http.py"; then ok
else bad "ARCHITECTURE.md says redirects are GET/HEAD only; _REDIRECTABLE_METHODS changed"; fi

printf '\n%d passed, %d failed, %d skipped\n' "$pass" "$fail" "$skip"
[ "$fail" -eq 0 ]
