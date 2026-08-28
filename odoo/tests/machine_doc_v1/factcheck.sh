#!/bin/bash
# odoo.tests machine-doc fact-check. Run from any cwd. Read-only.
#
# Every assertion DERIVES its expected value from the package and then checks
# that the docs agree. No expected value is written down here: a literal in this
# script would be a second copy of the tree, drifting independently of the
# first. Rule: `doc/coding_guidelines.rst` §1.4. Rationale: ADR-0043.
#
# WHY THIS ONE WAS LAST. `machine_doc.yml` discovered harnesses under
# `odoo/addons` and `addons`, and this package is under neither. So the document
# shipped, CLAUDE.md told every session to read it first, and the lane that
# exists to hold such documents to the tree could not see it -- not quarantined,
# not failing, simply out of range. The roots were widened to the repo in the
# same change that added this file, and the lane now warns for every machine_doc
# that still ships without a harness.
#
# WHAT IT PINS. The document was measured accurate when this was written: every
# file documented, every file on disk documented, every class it names defined.
# That is worth keeping rather than discovering again. The assertions are
# therefore about SHAPE -- the file inventory both ways, the public re-export
# surface, the names the prose promises are real -- and not about line counts,
# which this package's docs sensibly do not restate.
#
# Roots come from this script's own location, so a run always validates the tree
# it ships in.

set -u
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PKG="$(dirname "$SCRIPT_DIR")"                  # <repo>/odoo/tests
DOCS=("$SCRIPT_DIR"/*.md)

fail=0
pass=0
skip=0

ok()   { pass=$((pass + 1)); }
bad()  { fail=$((fail + 1)); printf '  FAIL  %s\n' "$1"; }
note() { skip=$((skip + 1)); printf '  SKIP  %s\n' "$1"; }

assert_doc_cites() {  # <needle> <human description>
    if grep -qF -- "$1" "${DOCS[@]}"; then ok; else bad "docs never cite $2 ($1)"; fi
}

printf '== odoo.tests machine_doc_v1 factcheck ==\n'

# ---------------------------------------------------------------- structure --
for f in index.md architecture.md conventions.md; do
    [ -f "$SCRIPT_DIR/$f" ] && ok || bad "missing $f"
done

# ------------------------------------------------------------ file inventory --
# Forward: every module in the package is a row of index.md's table. A file that
# exists and is undocumented is the half of drift a reader cannot detect,
# because nothing in the document looks wrong.
for f in "$PKG"/*.py; do
    base="$(basename "$f")"
    if grep -qF -- "\`$base\`" "$SCRIPT_DIR/index.md"; then ok
    else bad "index.md does not list $base"; fi
done

# Reverse: a row naming a module that is gone reads as current and sends the
# reader looking for it.
while read -r cited; do
    [ -z "$cited" ] && continue
    [ -f "$PKG/$cited" ] && ok || bad "index.md lists $cited, which no longer exists"
done < <(grep -oP '^\| `\K[a-z_0-9]+\.py(?=`)' "$SCRIPT_DIR/index.md")

# --------------------------------------------------------- public API surface --
# conventions.md: "odoo.tests re-exports exactly common.__all__ + Form/O2MProxy/
# M2MProxy", and warns that a public helper missing from __all__ will not
# resolve through `from odoo.tests import X`. Derive both halves; the claim is
# only useful while it is true.
api_report=$(python3 - "$PKG" <<'PY'
import ast, pathlib, sys

pkg = pathlib.Path(sys.argv[1])

init = ast.parse((pkg / "__init__.py").read_text())
imported = set()
star_from_common = False
for node in ast.walk(init):
    if isinstance(node, ast.ImportFrom):
        for alias in node.names:
            if alias.name == "*" and (node.module or "").endswith("common"):
                star_from_common = True
            else:
                imported.add(alias.asname or alias.name)

if not star_from_common:
    print("BAD|__init__.py no longer star-imports from common; conventions.md's "
          "\"re-exports exactly common.__all__\" claim is stale")
else:
    print("OK|star-import from common")

common = ast.parse((pkg / "common.py").read_text())
all_names = None
for node in common.body:
    if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "__all__":
        all_names = set(ast.literal_eval(node.value))
if all_names is None:
    print("BAD|common.py declares no __all__, which conventions.md says is the "
          "gate on the public surface")
    raise SystemExit(0)
print("OK|common.__all__ exists")

# The three names the doc says ride along beside common.__all__.
for extra in ("Form", "O2MProxy", "M2MProxy"):
    if extra in imported:
        print(f"OK|{extra} re-exported")
    else:
        print(f"BAD|conventions.md says odoo.tests re-exports {extra}; __init__.py "
              f"does not import it")

# Sanctioned convenience re-exports the doc says not to remove.
for name in ("Command", "patch", "mute_logger"):
    if name in all_names or name in imported:
        print(f"OK|{name} still re-exported")
    else:
        print(f"BAD|conventions.md calls {name} a sanctioned re-export; it is gone")
PY
)
while IFS='|' read -r verdict detail; do
    [ -z "$verdict" ] && continue
    [ "$verdict" = "OK" ] && ok || bad "$detail"
done <<< "$api_report"

# ------------------------------------------------------------- named symbols --
# Every class the prose names in backticks must be defined in the package. These
# are the names a reader greps for, and the doc is the reason they believe the
# name exists.
while read -r cls; do
    if grep -qhE "^class $cls\b" "$PKG"/*.py; then ok
    else bad "docs name class $cls, which is defined nowhere in the package"; fi
done < <(grep -ohP '`\K(BaseCase|TransactionCase|SingleTransactionCase|HttpCase|OdooSuite|OdooTestResult|TagsSelector|TestCursor|ChromeBrowser|Screencaster|Form|O2MForm|BenchmarkStats|Opener|Transport|JsonRpcException)(?=`)' "${DOCS[@]}" | sort -u)

# conventions.md pins ChromeBrowser as reachable through odoo.tests.common even
# though it lives in browser.py, because bus/base tests and web tooling patch it
# there. An import that stops re-exporting it breaks those mocks silently.
if grep -qE '\bChromeBrowser\b' "$PKG/common.py"; then ok
else bad "conventions.md requires odoo.tests.common.ChromeBrowser to stay a valid attribute; common.py no longer names it"; fi

# ---------------------------------------------------- environment variables ---
# Each env var the prose names must be read somewhere in the package. A doc that
# names a variable nothing reads sends an operator configuring a no-op.
while read -r var; do
    if grep -qhF -- "\"$var\"" "$PKG"/*.py || grep -qhF -- "'$var'" "$PKG"/*.py; then ok
    else bad "docs name env var $var, which the package never reads"; fi
done < <(grep -ohP '`\K(ODOO_[A-Z_]+)(?=`)' "${DOCS[@]}" | sort -u)

# --------------------------------------------------- backticked path sweep ----
# `odoo/CLAUDE.md` holds these directories to an invariant: a backticked path
# asserts that one particular file exists, so a deliberately-absent file -- or
# one in a sibling repo CI never checks out -- is named in PLAIN PROSE instead.
path_report=$(python3 - "$SCRIPT_DIR" "$PKG" <<'PY'
import pathlib, re, sys

doc_dir, pkg = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
repo = pkg.parent.parent                        # <repo>/odoo/tests -> <repo>
TOKEN = re.compile(r"`([A-Za-z0-9_./-]+\.(?:py|xml|js|md|csv|sh))`")
SIBLINGS = ("agromarin/", "agromarin-knowledge/", "enterprise/", "design-themes/")

if not (repo / "odoo-bin").exists():
    print("BAD|repo root misresolved (no odoo-bin at %s) -- sweep would be blind" % repo)
    raise SystemExit(0)

for doc in sorted(doc_dir.glob("*.md")):
    for token in sorted({m.group(1) for m in TOKEN.finditer(doc.read_text())}):
        if token.startswith(SIBLINGS):
            print(f"BAD|{doc.name} backticks {token}, which lives in a sibling "
                  f"checkout CI does not have -- name it in plain prose")
            continue
        if any((base / token).exists() for base in (doc_dir, pkg, repo)):
            print(f"OK|{token}")
        elif list(pkg.rglob(pathlib.PurePath(token).name)):
            print(f"OK|{token}")
        else:
            print(f"BAD|{doc.name} backticks {token}, which resolves to no file "
                  f"in this repository")
PY
)
while IFS='|' read -r verdict detail; do
    [ -z "$verdict" ] && continue
    [ "$verdict" = "OK" ] && ok || bad "$detail"
done <<< "$path_report"

# ------------------------------------------------------------------ summary --
printf '\n%d passed, %d failed, %d skipped\n' "$pass" "$fail" "$skip"
[ "$fail" -eq 0 ] || exit 1
