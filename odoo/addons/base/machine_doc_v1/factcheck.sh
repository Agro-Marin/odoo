#!/bin/bash
# base machine-doc fact-check. Run from any cwd. Read-only unless --update.
#
# Every assertion DERIVES its expected value from the module and then checks
# that the docs agree. No expected value is written down here: a literal in this
# script would be a second copy of the tree, drifting independently of the
# first. Rule: `doc/coding_guidelines.rst` §1.4. Rationale: ADR-0043.
#
# WHY THIS MODULE NEEDS ONE. `base` is the first module CLAUDE.md sends a
# session to and the last to get a harness -- until the `machine_doc.yml` roots
# were widened it was one of the docs the lane could not see. MODEL_MAP.md alone
# is 1,700 lines of inventory that becomes a reader's premises. Held by nothing,
# it had drifted:
#
#   - the Model Index gave `ir.mail_server` as `ir.mail.server`, and
#     ARCHITECTURE.md twice more. There is no such model; env["ir.mail.server"]
#     raises, so the doc handed the reader a name that cannot work.
#   - it pointed at `models/product_template.py`-style paths that had been
#     renamed away (`properties_base_definition_mixin.py`), and at
#     `core/odoo/addons/base/`, a directory this repository does not have.
#   - `report.base.report_irmodulereference` was declared and named nowhere.
#   - TEST_TAGS.md claimed 85 files, 260 classes and 1,347 methods against a
#     tree holding 126, 684 and 3,424.
#
# THE COUNTING RULE IS PART OF THE CLAIM. Two sessions counted this module's
# tests on the same day and got 684/3424 and 681/3420. A "total test classes"
# figure means nothing until the document says what it counts, so `TEST_TAGS.md`
# now states the rule -- what unittest collects, a `test` prefix and not `test_`
# -- and `_test_inventory.py` derives to it. See that module's docstring.
#
# Roots come from this script's own location, so a run always validates the tree
# it ships in.

set -u
UPDATE=0
[ "${1:-}" = "--update" ] && UPDATE=1

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MOD="$(dirname "$SCRIPT_DIR")"                  # <repo>/odoo/addons/base
DOCS=("$SCRIPT_DIR"/*.md)

fail=0
pass=0
skip=0

ok()   { pass=$((pass + 1)); }
bad()  { fail=$((fail + 1)); printf '  FAIL  %s\n' "$1"; }
note() { skip=$((skip + 1)); printf '  SKIP  %s\n' "$1"; }

printf '== base machine_doc_v1 factcheck ==\n'

# ---------------------------------------------------------------- structure --
for f in ARCHITECTURE.md CONVENTIONS.md MODEL_MAP.md TEST_TAGS.md; do
    [ -f "$SCRIPT_DIR/$f" ] && ok || bad "missing $f"
done

# ------------------------------------------------------------ model inventory --
# Every model the module declares must be named by MODEL_MAP.md, and the Model
# Index must not invent one.
#
# `models/tests/` is excluded: `stub.model` there is a fixture built to exercise
# the name manager, not part of the module's surface, and documenting it would
# tell a reader it is something they can use.
model_report=$(python3 - "$MOD" "$SCRIPT_DIR/MODEL_MAP.md" <<'PY'
import ast, pathlib, re, sys

mod, doc_path = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
doc = doc_path.read_text()

declared = {}
for sub in ("models", "wizard", "populate", "report"):
    root = mod / sub
    if not root.is_dir():
        continue
    for path in sorted(root.rglob("*.py")):
        if "tests" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:
            print(f"BAD|{path.relative_to(mod)} does not parse; the inventory "
                  f"below cannot be trusted")
            continue
        for node in ast.walk(tree):
            if (isinstance(node, ast.Assign)
                    and getattr(node.targets[0], "id", "") == "_name"):
                try:
                    declared[ast.literal_eval(node.value)] = path.relative_to(mod)
                except ValueError:
                    pass

if not declared:
    print("BAD|no models found -- the scan is broken, not the module")
    raise SystemExit(0)

for name, path in sorted(declared.items()):
    print(f"OK|{name}" if name in doc
          else f"BAD|MODEL_MAP.md never names {name}, declared in {path}")

# Reverse, off the Model Index rows only. The prose legitimately names config
# parameters (`ir_attachment.location`), field paths and worked examples
# (`x.tag`) that look exactly like model names to a regex, so the index -- where
# a model is inventoried -- is what must match.
index = re.search(r"^## Model Index$(.*)", doc, re.M | re.S)
if index:
    for row in re.finditer(r"^\| `([a-z_0-9/]+\.py)` \| ([^|]+)\|", index.group(1), re.M):
        filename, models = row.group(1), row.group(2)
        # The lookbehind is load-bearing: rows use a `.act_window` shorthand for
        # "same prefix as the entry before me", and without it the match starts
        # after the dot and reads as a bare model name the module never declares.
        for cited in re.findall(r"(?<![.\w])[a-z][a-z_]*(?:\.[a-z_0-9]+)+", models):
            print(f"OK|index row {cited}" if cited in declared
                  else f"BAD|Model Index lists {cited} under {filename}, which the "
                       f"module does not declare")
PY
)
while IFS='|' read -r verdict detail; do
    [ -z "$verdict" ] && continue
    [ "$verdict" = "OK" ] && ok || bad "$detail"
done <<< "$model_report"

# ------------------------------------------------------------- file listing --
# Every file the Model Index names must exist. `report/` is in the search set:
# leaving it out is what made the report model's own row look like a dead
# reference the moment it was documented.
while read -r cited; do
    [ -z "$cited" ] && continue
    if [ -f "$MOD/models/$cited" ] || [ -f "$MOD/wizard/$cited" ] \
       || [ -f "$MOD/report/$cited" ] || [ -f "$MOD/populate/$cited" ]; then ok
    else bad "Model Index names $cited, which exists in no source directory"; fi
done < <(sed -n '/^## Model Index$/,$p' "$SCRIPT_DIR/MODEL_MAP.md" \
         | grep -oP '^\| `\K[a-z_0-9]+\.py(?=`)')

# ------------------------------------------------------------------- tests ---
# Every test module must be named by TEST_TAGS.md, which is the page a session
# reads to decide what to run.
for f in "$MOD"/tests/test_*.py; do
    base="$(basename "$f")"
    if grep -qF -- "$base" "$SCRIPT_DIR/TEST_TAGS.md"; then ok
    else bad "TEST_TAGS.md does not name test file $base"; fi
done

# TEST_TAGS.md's two file tables, its Statistics block and its Quick Reference
# header are DERIVED, not read. A count moves whenever anyone adds a test, so
# asserting alone turns every change into a doc chore and the gate into
# something people route around. `--update` regenerates them, carrying across
# the hand-written one-line descriptions by filename.
#
#     bash machine_doc_v1/factcheck.sh --update
if [ "$UPDATE" = 1 ]; then
    inventory=$(python3 "$SCRIPT_DIR/_test_inventory.py" "$MOD" --update)
    [ "$inventory" = "UPDATED" ] && printf '  UPDATED  TEST_TAGS.md inventory\n'
    ok
else
    inventory=$(python3 "$SCRIPT_DIR/_test_inventory.py" "$MOD")
    if [ "$inventory" = "CURRENT" ]; then ok
    else bad "TEST_TAGS.md's tables, Statistics or header disagree with tests/ — run factcheck.sh --update"; fi
fi

# --------------------------------------------------- backticked path sweep ----
# `odoo/CLAUDE.md` holds these directories to an invariant: a backticked path
# asserts that one particular file exists, so a deliberately-absent file -- or
# one in a sibling repo CI never checks out -- is named in PLAIN PROSE instead.
# All four pages located this module under a `core/` directory that does not
# exist, which is exactly the failure this sweep makes impossible to repeat.
path_report=$(python3 - "$SCRIPT_DIR" "$MOD" <<'PY'
import pathlib, re, sys

doc_dir, mod = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
repo = mod.parent.parent.parent                 # <repo>/odoo/addons/base -> <repo>
TOKEN = re.compile(r"`([A-Za-z0-9_./-]+\.(?:py|xml|js|csv|sh))`")
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
        if any((base / token).exists() for base in (doc_dir, mod, repo)):
            print(f"OK|{token}")
        elif list(mod.rglob(pathlib.PurePath(token).name)):
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
