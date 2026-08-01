#!/bin/bash
# Web module architecture fact-check. Run from any cwd. Read-only.
#
# Assertions DERIVE their expected value from the filesystem and check that the
# docs cite it (assert_doc_cites), rather than keeping a second copy of every
# number that can go stale independently.
#
# Roots are derived from this script's own location, so the run always validates
# the tree it ships in. Checks needing a sibling repo (enterprise) or the
# framework tree SKIP with a count when it is absent, so a single-repo checkout
# reports honestly instead of failing or silently passing.
#
# Overrides: VENV_PY, ODOO_CONF, FACTCHECK_DB.

set -u
# All roots derive from this script's location so the run validates the tree it
# ships in. Hardcoded absolute paths made a copied/CI checkout silently verify
# the ORIGINAL tree and report a clean pass.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WEB="$(dirname "$SCRIPT_DIR")"                 # <repo>/addons/web
REPO="$(cd "$WEB/../.." && pwd)"               # <repo>  (the odoo fork)
ADDONS="$(dirname "$REPO")"                    # <workspace>/addons
WORKSPACE="$(dirname "$ADDONS")"               # <workspace>
VENV_PY="${VENV_PY:-$WORKSPACE/venv/p314o19m/bin/python}"
[ -x "$VENV_PY" ] || VENV_PY="$(command -v python3)"
ODOO_CONF="${ODOO_CONF:-$WORKSPACE/config/p314o19m.conf}"
DOC="$WEB/machine_doc_v1"
PASS=0
FAIL=0
SKIP=0

assert_eq() {
    local name="$1" actual="$2" expected="$3"
    if [ "$actual" = "$expected" ]; then
        echo "PASS: $name [$actual]"; PASS=$((PASS+1))
    else
        echo "FAIL: $name — expected [$expected] got [$actual]"; FAIL=$((FAIL+1))
    fi
}
# Assert the docs cite the number the filesystem actually reports, instead of
# a label could read "= 44" while the expected value said 48, and still PASS).
assert_doc_cites() {
    # $1 = human name, $2 = actual value, $3 = printf-style grep pattern with %s
    local name="$1" actual="$2" pat="$3"
    local rendered; rendered=$(printf "$pat" "$actual")
    local hits; hits=$(grep -cE "$rendered" "$DOC/$4" 2>/dev/null || echo 0)
    if [ "$hits" -ge 1 ]; then
        echo "PASS: $name [doc cites $actual]"; PASS=$((PASS+1))
    else
        echo "FAIL: $name — filesystem says $actual, $4 does not cite it"; FAIL=$((FAIL+1))
    fi
}
# Assertions that need a sibling repo or the framework tree SKIP (loudly) when
# it is absent, so a single-repo CI checkout is not permanently red.
skip_missing() {
    # $1 = path that must exist, $2 = what is skipped, $3 = how many assertions
    # it covers, so the SKIP total counts unrun CHECKS, not skipped blocks.
    if [ -e "$1" ]; then return 1; fi
    echo "SKIP: $2 — $3 assertion(s) (no $1)"; SKIP=$((SKIP+$3)); return 0
}
assert_range() {
    local name="$1" actual="$2" lo="$3" hi="$4"
    if [ "$actual" -ge "$lo" ] && [ "$actual" -le "$hi" ]; then
        echo "PASS: $name [$actual in $lo..$hi]"; PASS=$((PASS+1))
    else
        echo "FAIL: $name — expected $lo..$hi got [$actual]"; FAIL=$((FAIL+1))
    fi
}

# ------- Module size -------
# (core/errors/stack_frames.js — native stack parsing + sourcemap consumer
# audit wave (core/lib/{chartjs,fullcalendar}.js, search/embedded_actions_bar,
# views/list/list_record_row.js, model/relational_model split files, ...)
# minus the deleted polyfills/ file and load_coordinator.js.
SRC_JS=$(find "$WEB/static/src" -name "*.js" -type f | wc -l)
assert_doc_cites "ARCHITECTURE cites the src JS count" "$SRC_JS" '%s JavaScript' ARCHITECTURE.md

# ------- Type coverage -------
# 656 = 658 total - 2 intentional exclusions (module_loader + service_worker)
assert_eq "@ts-check coverage" \
    "$(grep -rl "@ts-check" "$WEB/static/src" --include="*.js" 2>/dev/null | wc -l)" "$((SRC_JS - 2))"
assert_eq "Untyped JS files (intentional: module_loader + service_worker)" \
    "$(find "$WEB/static/src" -name "*.js" -type f -exec grep -L "@ts-check" {} + 2>/dev/null | wc -l)" "2"

# ------- Test scope -------
HOOT_JS=$(find "$WEB/static/tests" -name "*.test.js" 2>/dev/null | wc -l)
TESTS_JS=$(find "$WEB/static/tests" -name "*.js" -type f | wc -l)
# vendored static/lib/qunit/, the web.tests_assets / web.__assets_tests_call__ /
# web.qunit_suite_tests bundles and the /web/tests/legacy route are all gone.
# The Class/publicWidget suites were later deleted with the legacy namespace
assert_eq "Legacy QUnit tree deleted (static/tests/legacy)" \
    "$([ -d "$WEB/static/tests/legacy" ] && echo 1 || echo 0)" "0"
assert_eq "Vendored QUnit deleted (static/lib/qunit)" \
    "$([ -d "$WEB/static/lib/qunit" ] && echo 1 || echo 0)" "0"
assert_eq "No qunit bundles left in manifest" \
    "$(grep -c "qunit" "$WEB/__manifest__.py")" "0"
# no executable QUnit API usage remains.
assert_eq "No QUnit. references remain (legacy chain fully removed)" \
    "$(grep -rl "QUnit\." "$WEB/static/tests" --include="*.js" 2>/dev/null | wc -l)" "0"
assert_eq "No QUnit.test/QUnit.module calls anywhere in static/" \
    "$(grep -rE "QUnit\.(test|module)\(" "$WEB/static" --include="*.js" 2>/dev/null | wc -l)" "0"
assert_eq "legacy_js test tree deleted (suites retired with the namespace)" \
    "$([ -d "$WEB/static/tests/legacy_js" ] && echo 1 || echo 0)" "0"
assert_eq "lazyloader HOOT suite lives in tests/public" \
    "$(find "$WEB/static/tests/public" -name "lazyloader.test.js" 2>/dev/null | wc -l)" "1"

# ------- Reactivity migration progress -------
# File-count grep over-counts because reactive.js itself matches via docstring.
REACTIVE_PATTERN='^(\s*export\s+)?class\s+\w+\s+extends\s+Reactive\b'
SIGNALSTORE_PATTERN='^(\s*export\s+)?class\s+\w+\s+extends\s+SignalStore\b'

# Helper: count declarations in production code only (exclude tests + machine_doc + .md).
count_prod_decls() {
    local pattern="$1"
    local files
    files=$(grep -rEl "$pattern" "$ADDONS/" 2>/dev/null \
        | grep -v "machine_doc\|\.test\.js\|\.md$")
    if [ -z "$files" ]; then
        echo 0
    else
        echo "$files" | xargs grep -Ec "$pattern" \
            | awk -F: '{ s += $NF } END { print s+0 }'
    fi
}
reactive_prod=$(count_prod_decls "$REACTIVE_PATTERN")
#       — required deleting web_studio's parallel Reactive class at
#         enterprise/web_studio/static/src/client_action/utils.js:75-86 and replacing
#         8 .raw() callers with toRaw(this) from @odoo/owl in edition_flow.js.
#   Total: 22 of 22 production sites on SignalStore. 0 remaining on Reactive alias.
#   form_save_coordinator.js:60 to own the form save lifecycle (replacing
#   CONVENTIONS.md gotcha #12).  It extends SignalStore so its `status`
#   and `lastError` fields are observable from external readers.
#   axis is keepLast + the reactive model.isReady flag.
assert_eq "Reactive class declarations (production)" "$reactive_prod" "0"

reactive_web=$(grep -rEln "$REACTIVE_PATTERN" "$WEB/static/src" 2>/dev/null | wc -l)
assert_eq "Reactive class declarations in core/addons/web" "$reactive_web" "0"

if skip_missing "$ADDONS/enterprise" "SignalStore cross-repo declaration count" 1; then :; else
    signalstore=$(count_prod_decls "$SIGNALSTORE_PATTERN")
    assert_eq "SignalStore class declarations (production code)" "$signalstore" "32"
fi
assert_eq "load_coordinator.js stays deleted" \
    "$([ -f "$WEB/static/src/model/relational_model/load_coordinator.js" ] && echo 1 || echo 0)" "0"

# Verify web_studio's parallel Reactive class is gone — replaced by SignalStore + toRaw().
if skip_missing "$ADDONS/enterprise" "web_studio Reactive/raw assertions" 2; then :; else
web_studio_reactive_class=$(grep -c "^export class Reactive {" \
    "$ADDONS/enterprise/web_studio/static/src/client_action/utils.js" 2>/dev/null)
assert_eq "web_studio's parallel Reactive class (deleted)" "$web_studio_reactive_class" "0"

# Verify the .raw() callers were correctly migrated to toRaw(this).
web_studio_raw_calls=$(grep -rc "\.raw()" "$ADDONS/enterprise/web_studio/static/src" 2>/dev/null \
    | awk -F: '{ s += $NF } END { print s+0 }')
assert_eq "web_studio .raw() callers (replaced by toRaw(this))" "$web_studio_raw_calls" "0"
fi

# web_vitals_service.js captures LCP/FCP/CLS/TTFB/INP via PerformanceObserver
# (INP as a worst-observed P100 running max — a strict upper bound on the
# canonical Chromium P98) and beacons to /web/observability/cwv on pagehide.
# 2 matching files: the service itself + core/browser/browser.js, which now
# exposes window.PerformanceObserver through the browser abstraction.
rum_telemetry=$(grep -rln "PerformanceObserver\|web-vitals" "$WEB/static/src" 2>/dev/null | wc -l)
assert_eq "PerformanceObserver/web-vitals (service + browser abstraction)" "$rum_telemetry" "2"
assert_eq "web_vitals INP reducer keeps a worst-observed (P100) running max" \
    "$(grep -c 'metrics.inp = e.duration' "$WEB/static/src/services/web_vitals/web_vitals_service.js")" "1"
assert_eq "MODEL_MAP.md inp row no longer claims 'currently always null'" \
    "$(grep -c 'currently always null' "$WEB/machine_doc_v1/MODEL_MAP.md")" "0"
# Coverage in BOTH directions: every models/*.py has a section, every section
# has an index row, and every documented method actually exists. Cardinality
# checks miss a file that is simply never mentioned.
read -r mm_undoc mm_noidx mm_badmethod <<<"$("$VENV_PY" - "$WEB" <<'PYEOF' 2>/dev/null
import ast, re, pathlib, sys
web = pathlib.Path(sys.argv[1])
doc = (web / "machine_doc_v1/MODEL_MAP.md").read_text()
secs = re.findall(r"^### (models/[\w./]+\.py)([^\n]*)\n(.*?)(?=^### |\Z)", doc, re.S | re.M)
sec_files = {p.split("/")[-1] for p, _, _ in secs}
idx = {m.group(1) for m in re.finditer(r"^\| `([\w./]+\.py)` \|", doc, re.M)}
disk = {p.name for p in (web / "models").glob("*.py") if p.name != "__init__.py"}
bad = 0
for path, _, body in secs:
    f = web / path
    if not f.exists():
        bad += 1
        continue
    defined = {n.name for n in ast.walk(ast.parse(f.read_text()))
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    bad += sum(1 for m in re.finditer(r"^- `([a-zA-Z_]\w*)\(", body, re.M)
               if m.group(1) not in defined)
print(len(disk - sec_files), len(sec_files - idx), bad)
PYEOF
)"
assert_eq "MODEL_MAP.md documents every models/*.py" "${mm_undoc:-PARSE_FAILED}" "0"
assert_eq "MODEL_MAP.md index row exists for every section" "${mm_noidx:-PARSE_FAILED}" "0"
assert_eq "MODEL_MAP.md documents no method that does not exist" "${mm_badmethod:-PARSE_FAILED}" "0"
assert_eq "MODEL_MAP.md inp row documents the P100 running max" \
    "$(grep -c 'worst-observed interaction duration' "$WEB/machine_doc_v1/MODEL_MAP.md")" "1"

# navigator.sendBeacon() call sites (5 files).
sendbeacon_files=$(grep -rlE "sendBeacon[?.]*\\(" "$WEB/static/src" --include="*.js" 2>/dev/null | wc -l)
assert_eq "sendBeacon call sites (start + module_loader + web_vitals + record_save + error_beacon)" "$sendbeacon_files" "5"

# Verify the observability controller is wired in.
observability_controller=$([ -f "$WEB/controllers/observability.py" ] && echo 1 || echo 0)
assert_eq "observability.py controller exists" "$observability_controller" "1"
observability_registered=$(grep -c "from . import observability" "$WEB/controllers/__init__.py" 2>/dev/null)
assert_eq "observability registered in controllers/__init__.py" "$observability_registered" "1"

# Phase 2: queryable model + dashboard view.
cwv_model=$([ -f "$WEB/models/web_cwv_metric.py" ] && echo 1 || echo 0)
assert_eq "web.cwv.metric model exists (Phase 2)" "$cwv_model" "1"
cwv_views=$([ -f "$WEB/views/web_cwv_metric_views.xml" ] && echo 1 || echo 0)
assert_eq "cwv views XML exists" "$cwv_views" "1"
cwv_model_registered=$(grep -c "from . import web_cwv_metric" "$WEB/models/__init__.py" 2>/dev/null)
assert_eq "web_cwv_metric registered in models/__init__.py" "$cwv_model_registered" "1"
cwv_views_in_manifest=$(grep -c "web_cwv_metric_views.xml" "$WEB/__manifest__.py" 2>/dev/null)
assert_eq "cwv views XML registered in manifest" "$cwv_views_in_manifest" "1"
cwv_acl=$(grep -c "model_web_cwv_metric" "$WEB/security/ir.model.access.csv" 2>/dev/null)
assert_eq "cwv ACL row in ir.model.access.csv" "$cwv_acl" "1"

# Phase 3: sampling + retention.
cwv_gc_method=$(grep -c "_gc_old_metrics" "$WEB/models/web_cwv_metric.py" 2>/dev/null)
assert_eq "_gc_old_metrics retention method" "$cwv_gc_method" "3"
cwv_cron_data=$([ -f "$WEB/data/web_cwv_metric_data.xml" ] && echo 1 || echo 0)
assert_eq "cwv cron data file exists" "$cwv_cron_data" "1"
cwv_cron_in_manifest=$(grep -c "web_cwv_metric_data.xml" "$WEB/__manifest__.py" 2>/dev/null)
assert_eq "cwv cron registered in manifest" "$cwv_cron_in_manifest" "1"
cwv_session_param=$(grep -c '"cwv_sample_rate":' "$WEB/models/ir_http.py" 2>/dev/null)
assert_eq "cwv_sample_rate key present in session_info dict" "$cwv_session_param" "1"
cwv_js_sampling=$(grep -c "session.cwv_sample_rate" "$WEB/static/src/services/web_vitals/web_vitals_service.js" 2>/dev/null)
assert_eq "JS service reads sample_rate from session" "$cwv_js_sampling" "1"

# ------- Accessibility instrumentation -------
assert_eq "axe-core references" \
    "$(grep -rln "axe-core\|axeCore" "$WEB/static/src" "$WEB/static/tests" 2>/dev/null | wc -l)" "0"

css_decls=$(grep -rh "^\s*--[a-zA-Z]" "$WEB/static/src" --include="*.scss" 2>/dev/null | wc -l)
assert_range "CSS custom property declarations" "$css_decls" 300 500
css_uses=$(grep -rh "var(--" "$WEB/static/src" --include="*.scss" 2>/dev/null | wc -l)
assert_range "var(--*) usages" "$css_uses" 350 450

assert_eq "form_controller distinct top-level dirs" \
    "$(grep "^import" "$WEB/static/src/views/form/form_controller.js" \
        | grep -oE "@web/[a-z_]+" | sort -u | wc -l)" "7"

assert_eq "legacy/ namespace deleted" \
    "$([ -d "$WEB/static/src/legacy" ] && echo 1 || echo 0)" "0"
assert_eq "early-boot lazyloader+minimal_dom relocated to public/" \
    "$(ls "$WEB/static/src/public/lazyloader.js" "$WEB/static/src/public/minimal_dom.js" 2>/dev/null | wc -l)" "2"
assert_eq "frontend boot extracted to public/public_boot(.js/_instance.js)" \
    "$(ls "$WEB/static/src/public/public_boot.js" "$WEB/static/src/public/public_boot_instance.js" 2>/dev/null | wc -l)" "2"

# Phase 1 added a `_pl(count, forms)` helper in core/l10n/translation.js that
# uses Intl.PluralRules to select the right singular/plural form for the
# active locale's CLDR rules.  Each form is an independent `_t()` result, so
# the existing .pot extractor still finds every msgid.  This delivers
# correct one/other behavior (en, es, fr, …) and degrades gracefully to the
# "other" form for unprovided categories on richer-plural locales (ru, pl,
# ar).  Real msgid_plural / msgstr[N] gettext extraction needs Python tooling
# work in core/odoo/tools/translate.py and is tracked as Phase 2 — the
# `ngettext functions` assertion stays at 0 until that lands.
assert_eq "Intl.PluralRules used in core/l10n (Phase 1 helper)" \
    "$(grep -rln "Intl\.PluralRules" "$WEB/static/src/core/l10n" 2>/dev/null | wc -l)" "1"
assert_eq "ngettext functions (Phase 2 deferred — needs Python extractor)" \
    "$(grep -rln "ngettext\|\bngt\b" "$WEB/static/src" 2>/dev/null | wc -l)" "0"
# `_pl` is the canonical export name; lock both the export and the call-site
# convention so a future rename trips a CI assertion.
assert_eq "translation.js exports _pl" \
    "$(grep -c "^export function _pl(" "$WEB/static/src/core/l10n/translation.js")" "1"
assert_eq "formatX2many uses _pl" \
    "$(grep -c "_pl(count, {" "$WEB/static/src/core/formatters.js")" "1"
# The plural categories come from Intl.LDMLPluralRule, not a hand-maintained
# list, so assert the type binding rather than the six category names.
assert_eq "_pl forms are typed by Intl.LDMLPluralRule" \
    "$(grep -c 'Intl.LDMLPluralRule' "$WEB/static/src/core/l10n/translation.js")" "1"
assert_eq "_pl selects via Intl.PluralRules with an 'other' fallback" \
    "$(grep -c 'forms\[category\] ?? forms.other' "$WEB/static/src/core/l10n/translation.js")" "1"

# ------- OWL bundle -------
assert_eq "OWL bundle bytes" "$(stat -c '%s' "$WEB/static/lib/owl/owl.es.js")" "233543"
assert_eq "OWL version string" \
    "$(grep -oE 'version = "[0-9]+\.[0-9]+\.[0-9]+"' "$WEB/static/lib/owl/owl.es.js" | head -1)" \
    'version = "2.8.3"'
assert_eq "OWL ships ESM only (UMD build dropped)" \
    "$(ls "$WEB/static/lib/owl/" | tr '\n' ' ')" "owl.es.js "

# ------- Service worker -------
# The constant was renamed; the strategy is what matters, so assert the
# handler and its dispatch rather than a since-renamed identifier.
assert_range "stale-while-revalidate strategy wired in SW" \
    "$(grep -c "staleWhileRevalidate" "$WEB/static/src/service_worker.js")" 2 3

# ------- Security: XSS surface (NEW assertions) -------
assert_eq ".innerHTML = usages (gated: isMarkup() in html.js, instanceof Markup in colibri.js)" \
    "$(grep -rhE "\.innerHTML[[:space:]]*=[^=]" "$WEB/static/src" --include="*.js" 2>/dev/null | wc -l)" "2"
assert_eq ".outerHTML = usages" \
    "$(grep -rhE "\.outerHTML[[:space:]]*=[^=]" "$WEB/static/src" --include="*.js" 2>/dev/null | wc -l)" "0"
assert_eq "eval()/new Function() usages" \
    "$(grep -rE "\beval\(|new Function\(" "$WEB/static/src" --include="*.js" 2>/dev/null | wc -l)" "0"
markup_importers=$("$VENV_PY" - "$WEB/static/src" <<'PYEOF' 2>/dev/null
import re, pathlib, sys
imp = re.compile(r'import\s*\{([^}]*)\}\s*from\s*["\']([^"\']+)["\']', re.S)
n = 0
for p in sorted(pathlib.Path(sys.argv[1]).rglob("*.js")):
    t = p.read_text(errors="ignore")
    for m in imp.finditer(t):
        if "markup" in [x.strip().split(" as ")[0].strip() for x in m.group(1).split(",")]:
            n += 1
            break
print(n)
PYEOF
)
assert_eq "markup() trust-hatch import sites" "${markup_importers:-PARSE_FAILED}" "15"

# The G3 startViewTransition wrap was removed from action_container.js; only
# an explanatory comment remains (it explains why the API can't wrap OWL's
# render directly).  Lock the removal so the feature doesn't half-return
# without docs/factcheck being updated.
assert_eq "ActionContainer no longer calls document.startViewTransition" \
    "$(grep -cE 'document\.startViewTransition\(' "$WEB/static/src/webclient/actions/action_container.js")" "0"
assert_eq "No startViewTransition call anywhere in static/src" \
    "$(grep -rE 'startViewTransition\(' "$WEB/static/src" --include="*.js" 2>/dev/null | wc -l)" "0"

# Convention enforced via CONVENTIONS.md gotcha #13 (prototype-only patching
# for classes, plain-object patching for env/services; never patch a frozen
# ES-module namespace).  No factcheck assertion: a coarse "files combining
# import * as with patch()" grep produced 44 false positives (mostly test
# files where the two patterns are used independently).  The right
# not a regex.

# orm.retry() default must match the documented boot-path budget in CONVENTIONS.md
# (retry: 1).  Pre-G5 the source defaulted to 3, drifting from documented intent.
# A bare orm.retry().call(...) silently got 3 retries against the rationale of
# "cap user-perceived delay at one backoff interval ~200ms".
assert_eq "orm.retry() default value [1]" \
    "$(grep -c 'retry(options = 1)' "$WEB/static/src/services/orm_service.js")" "1"
assert_eq "orm.retry() does NOT default to 3" \
    "$(grep -c 'retry(options = 3)' "$WEB/static/src/services/orm_service.js")" "0"

# ------- Production bundle sizes (NEW — from DB ir_attachment) -------
FACTCHECK_DB="${FACTCHECK_DB:-hoot_web}"
if psql -d "$FACTCHECK_DB" -c "SELECT 1" >/dev/null 2>&1; then
    : # bundle-size assertions removed: they measured a prod-restore DB,
      # not this source tree, and the ESM split made the figure meaningless.
else
    echo "SKIP: bundle size assertions (DB $FACTCHECK_DB unavailable; set FACTCHECK_DB=...)"
    SKIP=$((SKIP+1))
fi

# Each pair locks both directions: the new wording must be present AND the
# stale wording must be gone.  This catches the failure mode where a fix
# lands in code but the cited doc keeps describing the old behavior — the
#
# Precedent: STATE_MANAGEMENT.md still described an "Optimistic-locking
# divergence" three weeks after record_save.js:80-83 fixed it; CONVENTIONS.md
# gotcha #12 still described "5 `true` call sites" with positional booleans
# after FormSaveCoordinator replaced them; ARCHITECTURE.md still claimed
# "615 JS files" after five new src files landed.
#
# Adding a doc-consistency assertion alongside every code-state assertion
# makes the doc-vs-code drift fail loud at CI time instead of silently
# misleading the next code reader.

# 1. Optimistic locking is now FIELD-SCOPED (known_values baseline map,
#    commits 4ecbac1e7cb + d08cb6b77a8) — the client no longer sends
#    last_write_date; the server keeps it only as a legacy fallback.
#    Both save paths must send the baseline, and the docs must describe
#    the new mechanism.
assert_eq "STATE_MANAGEMENT urgent-save: stale 'divergence' wording removed" \
    "$(grep -c 'Optimistic-locking divergence' "$WEB/machine_doc_v1/STATE_MANAGEMENT.md")" "0"
assert_eq "STATE_MANAGEMENT urgent-save: optimistic-locking parity documented" \
    "$(grep -c 'Optimistic-locking parity' "$WEB/machine_doc_v1/STATE_MANAGEMENT.md")" "1"
# The builder was extracted to concurrency_baseline.js so record_save.js and
# dynamic_list.js cannot drift; assert the shared module + its consumer.
assert_eq "concurrency_baseline.js exports buildConcurrencyBaseline" \
    "$(grep -c 'export function buildConcurrencyBaseline' "$WEB/static/src/model/relational_model/concurrency_baseline.js")" "1"
assert_eq "record_save.js uses the shared concurrency baseline builder" \
    "$(grep -c 'buildConcurrencyBaseline(' "$WEB/static/src/model/relational_model/record_save.js")" "1"
assert_eq "record_save.js sends known_values on BOTH paths (urgent + normal)" \
    "$(grep -c 'known_values' "$WEB/static/src/model/relational_model/record_save.js")" "2"
assert_eq "record_save.js no longer sends last_write_date" \
    "$(grep -c 'last_write_date' "$WEB/static/src/model/relational_model/record_save.js")" "0"
assert_eq "server: web_read.py implements the _check_concurrent_field_changes family" \
    "$(grep -c 'def _check_concurrent_field_changes' "$WEB/models/web_read.py")" "4"
assert_eq "CONVENTIONS gotcha #9 documents known_values (field-scoped locking)" \
    "$(grep -c 'known_values' "$WEB/machine_doc_v1/CONVENTIONS.md")" "2"
assert_eq "STATE_MANAGEMENT documents known_values" \
    "$(grep -c 'known_values' "$WEB/machine_doc_v1/STATE_MANAGEMENT.md")" "3"

# 2. FormSaveCoordinator — CONVENTIONS.md gotcha #12 must reflect the rewrite.
assert_eq "CONVENTIONS gotcha #12: stale '5 \`true\` call sites' wording removed" \
    "$(grep -c '5 \`true\` call sites' "$WEB/machine_doc_v1/CONVENTIONS.md")" "0"
assert_eq "CONVENTIONS gotcha #12: mentions FormSaveCoordinator" \
    "$(grep -c 'FormSaveCoordinator' "$WEB/machine_doc_v1/CONVENTIONS.md")" "2"
# Cite-fingerprint: the doc cites form_save_coordinator.js; verify the file
# exists and exports a FormSaveCoordinator class extending SignalStore.
assert_eq "form_save_coordinator.js exports FormSaveCoordinator class" \
    "$(grep -c 'export class FormSaveCoordinator extends SignalStore' "$WEB/static/src/views/form/form_save_coordinator.js")" "1"
# Cite-fingerprint: the doc cites the named-option API (errorMode); verify
# the typedef declares the three documented modes verbatim.  Counting raw
# occurrences of the strings overcounts (8) because they appear in JSDoc,
# default-value bindings, and dispatch arms; targeting the canonical
# typedef line locks the public contract.
assert_eq "FormSaveCoordinator errorMode typedef declares three modes" \
    "$(grep -cE '^\s\*\s+errorMode\?: "dialog" \| "rethrow" \| "silent"' "$WEB/static/src/views/form/form_save_coordinator.js")" "1"

assert_eq "ARCHITECTURE.md no stale JS file counts (615/621/649/657)" \
    "$(grep -cE '(615|621|649|657) (JavaScript|JS)' "$WEB/machine_doc_v1/ARCHITECTURE.md")" "0"
assert_doc_cites "ARCHITECTURE.md JS count cited in prose" "$SRC_JS" '%s JavaScript' ARCHITECTURE.md
# The other site is a markdown table cell `| JavaScript (src) | N (...)`.
assert_doc_cites "ARCHITECTURE.md JS table cell" "$SRC_JS" '\| JavaScript \(src\) \| %s ' ARCHITECTURE.md

# 4. Pattern 4 inventory — STATE_MANAGEMENT.md should enumerate verified sites
#    rather than implying an open population.
assert_eq "STATE_MANAGEMENT lists Pattern 4 sites table" \
    "$(grep -c 'Pattern 4 sites' "$WEB/machine_doc_v1/STATE_MANAGEMENT.md")" "1"

#    - reactive.js exports SignalStore only (no `export const Reactive`)
#    - reactive.test.js references SignalStore, not Reactive
#    - eslint.config.mjs has no Reactive-import rule (rule is now unenforceable
#      anyway: the export does not exist, so the import fails at module-load)
assert_eq "reactive.js does not export Reactive (alias dropped)" \
    "$(grep -c 'export const Reactive' "$WEB/static/src/core/utils/reactive.js")" "0"
assert_eq "reactive.js still exports SignalStore" \
    "$(grep -c 'export class SignalStore' "$WEB/static/src/core/utils/reactive.js")" "1"
assert_eq "reactive.test.js imports SignalStore (not Reactive)" \
    "$(grep -c 'import.*SignalStore.*@web/core/utils/reactive' "$WEB/static/tests/core/reactive.test.js")" "1"
assert_eq "reactive.test.js does not import Reactive" \
    "$(grep -cE 'import\s*\{[^}]*\bReactive\b[^}]*\}\s*from\s*"@web/core/utils/reactive"' "$WEB/static/tests/core/reactive.test.js")" "0"
if skip_missing "$REPO/eslint.config.mjs" "eslint Reactive-import rule assertion" 1; then :; else
    assert_eq "eslint.config.mjs no longer carries the Reactive-import rule" \
        "$(grep -c "imported.name='Reactive'" "$REPO/eslint.config.mjs")" "0"
fi

# 6. Per-section JS file counts — reality checks against the filesystem.
#    (Top-line total is covered by "JS file count" above.  The former
#    DIRECTORY_MAP.md's per-directory map.)
# Per-section subtotals are NOT pinned to literals here any more. The layer
# loop in section 15 asserts that ARCHITECTURE.md cites whatever the filesystem
# reports for each layer, which catches the same drift without keeping a second
# copy of the numbers to go stale (this list had webclient/ at 61 against a real
# 63, and never listed public/ at all).

# 7. Gotcha #10 cite-fingerprint: archiveEnabled consolidated into
#    view_utils.computeArchiveEnabled(readonlySource, presenceSource).
#    Form gates presence on model.root.activeFields; multi-record passes
#    only props.fields.  The x_active fallback now lives in the shared
#    helper, not in form_controller.
assert_eq "view_utils exports computeArchiveEnabled(fields, { presentIn })" \
    "$(grep -c 'export function computeArchiveEnabled(fields, { presentIn = fields } = {})' "$WEB/static/src/views/view_utils.js")" "1"
assert_eq "computeArchiveEnabled has the x_active fallback" \
    "$(grep -cE 'for \(const fieldName of \["active", "x_active"\]\)' "$WEB/static/src/views/view_utils.js")" "1"
assert_eq "form_controller has archiveEnabled getter" \
    "$(grep -c 'get archiveEnabled()' "$WEB/static/src/views/form/form_controller.js")" "1"
assert_eq "form_controller delegates with the activeFields presence gate" \
    "$(grep -c 'presentIn: this.model.root.activeFields' "$WEB/static/src/views/form/form_controller.js")" "1"
assert_eq "multi_record_controller delegates to computeArchiveEnabled" \
    "$(grep -c 'computeArchiveEnabled(this.props.fields)' "$WEB/static/src/views/multi_record_controller.js")" "1"
assert_eq "CONVENTIONS gotcha #10 names the computeArchiveEnabled form call" \
    "$(grep -c 'presentIn: this.model.root.activeFields' "$WEB/machine_doc_v1/CONVENTIONS.md")" "1"
assert_eq "CONVENTIONS gotcha #10 carries no stale form_controller.js line cites" \
    "$(grep -cE 'form_controller.js:[0-9]' "$WEB/machine_doc_v1/CONVENTIONS.md")" "0"

# 8. Gotcha #5 cite-fingerprint: /web/image route count (claim: 17 patterns).
assert_eq "binary.py /web/image route mentions match doc claim (17)" \
    "$(grep -cE '/web/image' "$WEB/controllers/binary.py")" "20"

# 9. Gotcha #6 cite-fingerprint: Chart.js is lazy-loaded as a real ES module
#     via core/lib/chartjs.js (dynamic import of the `chart.js` import-map
#     specifier + live-bound `Chart` export).  The old
#     loadBundle("web.chartjs_lib") classic-script path is gone, as is the
#     manifest bundle itself.  FullCalendar follows the same pattern.
assert_eq "graph_renderer.js awaits loadChartJS()" \
    "$(grep -c 'await loadChartJS()' "$WEB/static/src/views/graph/graph_renderer.js")" "1"
assert_eq "graph_renderer.js imports from @web/core/lib/chartjs" \
    "$(grep -c '@web/core/lib/chartjs' "$WEB/static/src/views/graph/graph_renderer.js")" "1"
assert_eq "core/lib/chartjs.js dynamic-imports chart.js" \
    "$(grep -c 'import("chart.js")' "$WEB/static/src/core/lib/chartjs.js")" "1"
assert_eq "core/lib/fullcalendar.js exports loadFullCalendar" \
    "$(grep -c 'export async function loadFullCalendar' "$WEB/static/src/core/lib/fullcalendar.js")" "1"
assert_eq "manifest no longer declares web.chartjs_lib / web.fullcalendar_lib" \
    "$(grep -cE 'chartjs_lib|fullcalendar_lib' "$WEB/__manifest__.py")" "0"
assert_eq "no loadBundle(chartjs_lib) call sites remain in static/src" \
    "$(grep -rc 'loadBundle("web.chartjs_lib")' "$WEB/static/src" --include="*.js" 2>/dev/null | awk -F: '{s+=$NF} END {print s+0}')" "0"
assert_eq "CONVENTIONS gotcha #6 documents loadChartJS" \
    "$(grep -c 'loadChartJS' "$WEB/machine_doc_v1/CONVENTIONS.md")" "1"
# Cite-fingerprint: the `set groupId` setter is the *canonical exception* to
# Pattern 4 — it must clear sample data on the same microtask as the groupId
# deferred cleanup breaks 3 sample-data integration tests.
#
# Per the no-explanatory-comments rule, the source carries only a SELF-CONTAINED
# eslint-disable and STATE_MANAGEMENT.md is the rationale of record. So lock:
# the setter line, a pragma that explains itself without pointing outside the
# line, and the rationale (incl. the reverted commit) living in the doc.
# The previous version asserted the rationale lived in the source, which the
# "see comment above" with nothing above it.
KANBAN_JS="$WEB/static/src/views/kanban/kanban_controller.js"
assert_eq "kanban_controller.js groupId setter (canonical Pattern 4 exception)" \
    "$(grep -c 'set groupId(groupId)' "$KANBAN_JS")" "1"
assert_eq "kanban_controller.js keeps the no-restricted-syntax pragma" \
    "$(grep -c 'eslint-disable-next-line no-restricted-syntax' "$KANBAN_JS")" "1"
assert_eq "kanban pragma is self-contained (no dangling 'see comment above')" \
    "$(grep -c 'see comment above' "$KANBAN_JS")" "0"
assert_eq "kanban pragma points at the rationale of record" \
    "$(grep -c 'STATE_MANAGEMENT.md' "$KANBAN_JS")" "1"
assert_eq "STATE_MANAGEMENT.md carries the reverted-migration commit" \
    "$(grep -c '19fb5d01bb81' "$DOC/STATE_MANAGEMENT.md")" "1"
assert_eq "STATE_MANAGEMENT.md no longer points at a source comment block" \
    "$(grep -c 'comment block above the setter' "$DOC/STATE_MANAGEMENT.md")" "0"

#     The `GlobalRegistryCategories` interface in @types/registries/registries.d.ts
#     `effects: EffectsRegistryItemShape` (correct).  Cross-repo grep across
#     core/enterprise/agromarin showed zero consumers of the typo'd name — it was
#     pure dead type, contributing nothing to type checking and confusing readers.
#     Removed the typo line; locked it here so it doesn't get re-introduced by a
#     future copy/paste from old commit history.
assert_eq "registries.d.ts: typo'd 'effetcs' key removed" \
    "$(grep -c "^\s*effetcs:" "$WEB/static/src/@types/registries/registries.d.ts")" "0"
assert_eq "registries.d.ts: 'effects' key still declared" \
    "$(grep -c "^\s*effects: EffectsRegistryItemShape;" "$WEB/static/src/@types/registries/registries.d.ts")" "1"
# Cross-repo: confirm no dangling consumer of the typo'd name slipped in
# through downstream addons after the type definition was cleaned up.
# Exclude this script itself (it cites the typo in its own docstring +
# assertion strings, which would self-trigger), machine_doc directories
# (where forensic notes about the fix may legitimately mention the typo),
# and .git/ (the reflog records past commits whose messages or diffs
assert_eq "no 'effetcs' consumers across active repos" \
    "$(grep -rln "effetcs" \
        "$ADDONS/odoo" \
        "$ADDONS/enterprise" \
        "$ADDONS/agromarin" \
        --exclude-dir=machine_doc_v1 \
        --exclude-dir=.git 2>/dev/null | wc -l)" "0"

# fix stays in lockstep with code.  Catches the failure mode "doc was updated
# but the code subsequently shifted underneath it".

# 11. dedup proxy on ORM — ARCHITECTURE.md must document it; rpc.js must
assert_eq "orm_service.js exports 'get dedup' proxy" \
    "$(grep -cE '^\s+get dedup\(\)' "$WEB/static/src/services/orm_service.js")" "1"
# RPC_SETTINGS is a multi-line Set literal; match the "dedup" member directly.
assert_eq "rpc.js RPC_SETTINGS whitelist includes 'dedup'" \
    "$(grep -cE '^\s*"dedup",' "$WEB/static/src/core/network/rpc.js")" "1"
assert_eq "ARCHITECTURE.md documents orm.dedup proxy" \
    "$(grep -cE '\*\*`orm\.dedup`\*\*' "$WEB/machine_doc_v1/ARCHITECTURE.md")" "1"
assert_eq "ARCHITECTURE.md rpc.js whitelist mentions all 6 keys" \
    "$(grep -cE 'cache, silent, headers, timeout, retry, dedup' "$WEB/machine_doc_v1/ARCHITECTURE.md")" "1"

# 12. Vendored versions are owned by static/lib/versions.json; the doc must
#     defer to it rather than keep a second copy that can drift.
assert_eq "ARCHITECTURE.md defers to versions.json" \
    "$(grep -c 'versions.json' "$WEB/machine_doc_v1/ARCHITECTURE.md")" "3"
assert_eq "versions.json pins every static/lib library dir" \
    "$(python3 -c "import json;print(len(json.load(open('$WEB/static/lib/versions.json'))['libs']))")" "17"
assert_eq "ARCHITECTURE.md no stale fullcalendar 6.1.20 / 7.0.0-rc.3" \
    "$(grep -cE 'fullcalendar.{0,30}(6\.1\.20|7\.0\.0-rc)' "$WEB/machine_doc_v1/ARCHITECTURE.md")" "0"
assert_eq "fullcalendar vendored bundle is v7 (final 7.0.0 present in source)" \
    "$(grep -c 'FullCalendar v7' "$WEB/static/lib/fullcalendar/fullcalendar.esm.js"):$(grep -m1 -coE 'v7\.0\.0' "$WEB/static/lib/fullcalendar/fullcalendar.esm.js")" "1:1"

# 13. STATE_MANAGEMENT.md phantom AppEvent.FORM_DIALOG_* events removed.
#     push()/pop() calls; the constants no longer exist in core/events.js.
assert_eq "STATE_MANAGEMENT.md no phantom FORM_DIALOG_ADD row" \
    "$(grep -c 'AppEvent.FORM_DIALOG_ADD' "$WEB/machine_doc_v1/STATE_MANAGEMENT.md")" "0"
assert_eq "STATE_MANAGEMENT.md no phantom FORM_DIALOG_REMOVE row" \
    "$(grep -c 'AppEvent.FORM_DIALOG_REMOVE' "$WEB/machine_doc_v1/STATE_MANAGEMENT.md")" "0"
assert_eq "core/events.js does not export FORM_DIALOG_ADD" \
    "$(grep -cE 'FORM_DIALOG_ADD\s*:' "$WEB/static/src/core/events.js")" "0"

# 14. ARCHITECTURE.md table counts — numeric claims locked.  Catches the
#     drift pattern that motivated this audit (counts grew, doc lagged).
PY_TESTS=$(find "$WEB/tests" -name "test_*.py" | wc -l)
assert_doc_cites "ARCHITECTURE.md File Counts: Python tests" "$PY_TESTS" '\| Python \(tests\) \| %s ' ARCHITECTURE.md
assert_doc_cites "ARCHITECTURE.md File Counts: JS tests total" "$TESTS_JS" '\| JavaScript \(tests\) \| %s \(incl' ARCHITECTURE.md
assert_doc_cites "ARCHITECTURE.md File Counts: Hoot suites" "$HOOT_JS" 'incl\. %s .\*\.test\.js' ARCHITECTURE.md
assert_eq "ARCHITECTURE.md File Counts: vendored libs = 92" \
    "$(grep -cE '\| JavaScript \(vendored libs\) \| 92 \|' "$WEB/machine_doc_v1/ARCHITECTURE.md")" "1"
assert_eq "static/lib JS file count = 92 (reality check)" \
    "$(find "$WEB/static/lib" -name "*.js" -type f | wc -l)" "92"

# 15. ARCHITECTURE.md JavaScript Architecture table — lock the Layer subtotals.
#     These mirror the per-section filesystem assertions but for the
#     ARCHITECTURE doc's view of the same numbers.
# Every layer row must cite the count the filesystem reports for that directory.
for layer_spec in "Primitives:core" "Components:components" "Services:services" \
                  "UI:ui" "Fields:fields" "Views:views" "Webclient:webclient" \
                  "Search:search" "Model:model" "Public:public"; do
    lname="${layer_spec%:*}"; ldir="${layer_spec##*:}"
    lcount=$(find "$WEB/static/src/$ldir" -name "*.js" -type f | wc -l)
    assert_doc_cites "ARCHITECTURE.md Layer: $lname ($ldir/)" "$lcount" \
        "\\| \\*\\*$lname\\*\\* \\| .$ldir/. \\|.*\\| %s JS \\|" ARCHITECTURE.md
done
assert_eq "ARCHITECTURE.md Layer table covers libs/" \
    "$(grep -cE '\| .libs/. \|' "$WEB/machine_doc_v1/ARCHITECTURE.md")" "1"

# 16. DIRECTORY_MAP.md header count — single source of truth for the dir total.
#     + search/embedded_actions_bar/.
SRC_DIRS=$(find "$WEB/static/src" -mindepth 1 -type d -not -path '*/.claude*' | wc -l)
assert_doc_cites "DIRECTORY_MAP.md header states the entry count" "$((SRC_DIRS + 1))" \
    '\\*\\*%s entries\\*\\*' DIRECTORY_MAP.md
# Set equality, not just cardinality: a phantom row plus a missing row cancel
# out in a count (they did — contact_statistics/ vs core/file_upload/).
map_only=$(comm -23 \
    <(grep -oE '^\| `[^`]+`' "$DOC/DIRECTORY_MAP.md" | sed 's/^| `//;s/`$//;s:/$::' | grep -v '^(root)$' | LC_ALL=C sort -u) \
    <(cd "$WEB/static/src" && find . -mindepth 1 -type d | sed 's:^\./::' | LC_ALL=C sort -u) | tr '\n' ' ')
disk_only=$(comm -13 \
    <(grep -oE '^\| `[^`]+`' "$DOC/DIRECTORY_MAP.md" | sed 's/^| `//;s/`$//;s:/$::' | grep -v '^(root)$' | LC_ALL=C sort -u) \
    <(cd "$WEB/static/src" && find . -mindepth 1 -type d | sed 's:^\./::' | LC_ALL=C sort -u) | tr '\n' ' ')
# Whole-table validation: every row's Files column must equal `ls <dir>/*.js`.
# Set equality alone let 39 wrong counts survive undetected.
dirmap_bad=$("$VENV_PY" - "$WEB" <<'PYEOF' 2>/dev/null
import re, pathlib, sys
web = pathlib.Path(sys.argv[1]); src = web / "static/src"
bad = 0
for ln in open(web / "machine_doc_v1/DIRECTORY_MAP.md"):
    m = re.match(r"\|\s*`([^`]+)`\s*\|\s*[^|]+\|\s*(\d+)\s*\|", ln)
    if not m:
        continue
    d, files = m.group(1), int(m.group(2))
    p = src if d == "(root)" else src / d.rstrip("/")
    if not p.is_dir() or len(list(p.glob("*.js"))) != files:
        bad += 1
print(bad)
PYEOF
)
# Every backticked source path in the docs must resolve to a real file.
# Scope is the whole workspace (docs cite enterprise and workspace-relative
# paths too). Excluded: route URLs, upstream package paths (dist/...), and
# load_coordinator.js, which is deliberately cited as absent.
if skip_missing "$REPO/odoo" "doc source-path resolution sweep" 1; then :; else
dead_refs=$("$VENV_PY" - "$DOC" "$WORKSPACE" "$REPO" "$WEB" <<'PYEOF' 2>/dev/null
import re, pathlib, sys, collections, os
doc_dir, ws, repo, web = (pathlib.Path(a) for a in sys.argv[1:5])
index = collections.defaultdict(list)
for base in ("addons/odoo", "addons/enterprise", "addons/agromarin", "addons/design-themes"):
    b = ws / base
    if not b.is_dir():
        continue
    for p in b.rglob("*"):
        if p.is_file():
            index[p.name].append(str(p))
SKIP_BASE = {"load_coordinator.js"}
bad = 0
for doc in sorted(doc_dir.glob("*.md")):
    for m in re.finditer(r"`([\w./\-]+\.(?:py|js|mjs|xml|json|yml|scss|csv|rst|md|sh))`", doc.read_text()):
        ref = m.group(1)
        base = ref.split("/")[-1]
        if ref.startswith(("/", ".", "dist/")) or base in SKIP_BASE:
            continue
        if (ws / ref).exists():
            continue
        # A ref beginning with a repo-root directory unambiguously means the
        # repo root, so a suffix match elsewhere must NOT satisfy it (that is
        # how `tooling/enable.sh` hid at addons/web/tooling/enable.sh).
        # `doc/` is ambiguous: the repo root has doc/adr/, the web module has
        # its own doc/ (COMPONENT_DIAGRAM, FLOW_DIAGRAM). Accept either root for
        # it; the rest are unambiguously repo-root.
        top = ref.split("/")[0]
        if top == "doc":
            if not ((repo / ref).exists() or (web / ref).exists()):
                bad += 1
            continue
        if top in {"tooling", "odoo", ".github"}:
            if not (repo / ref).exists():
                bad += 1
            continue
        if base not in index:
            bad += 1
        elif "/" in ref and not any(q.endswith(ref) for q in index[base]):
            bad += 1
print(bad)
PYEOF
)
assert_eq "docs reference no source path that does not exist" "${dead_refs:-PARSE_FAILED}" "0"
fi

# Every service registered in web must appear in ARCHITECTURE.md (as a table row
# or in the catch-all note), and every documented row must name the real file.
read -r svc_undoc svc_badpath <<<"$("$VENV_PY" - "$WEB" <<'PYEOF' 2>/dev/null
import re, pathlib, sys
web = pathlib.Path(sys.argv[1])
truth = {}
for p in (web / "static/src").rglob("*.js"):
    t = p.read_text(errors="ignore")
    aliases = {m.group(1) for m in re.finditer(
        r'(?:const|let|var)\s+(\w+)\s*=\s*registry\s*\.\s*category\(\s*["\']services["\']\s*\)', t)}
    pats = [r'registry\s*\.\s*category\(\s*["\']services["\']\s*\)\s*\.\s*add\(\s*["\']([^"\']+)["\']']
    pats += [rf'\b{re.escape(a)}\s*\.\s*add\(\s*["\']([^"\']+)["\']' for a in aliases]
    for pat in pats:
        for m in re.finditer(pat, t):
            truth[m.group(1)] = str(p.relative_to(web / "static/src"))
doc = (web / "machine_doc_v1/ARCHITECTURE.md").read_text()
rows = dict(re.findall(r'^\|\s*`([\w.]+)`\s*\|\s*`([^`]+)`\s*\|', doc, re.M))
note = re.search(r'> Additional webclient-level services:(.*?)\n\n', doc, re.S)
note = set(re.findall(r'`(\w+)`', note.group(1))) if note else set()
covered = set(rows) | note
print(len(set(truth) - covered),
      sum(1 for n, f in rows.items() if n in truth and f != truth[n]))
PYEOF
)"
# Registry schema coverage: CONVENTIONS gotcha #11 must cite the real
# validated/total split rather than a snapshot that silently rots.
read -r reg_val reg_tot <<<"$("$VENV_PY" - "$WEB/static/src" <<'PYEOF' 2>/dev/null
import re, pathlib, sys
cats, validated = set(), set()
for p in pathlib.Path(sys.argv[1]).rglob("*.js"):
    t = p.read_text(errors="ignore")
    cats |= set(re.findall(r'registry\s*\.\s*category\(\s*["\']([^"\']+)["\']\s*\)', t))
    al = dict(re.findall(
        r'(?:const|let|var)\s+(\w+)\s*=\s*registry\s*\.\s*category\(\s*["\']([^"\']+)["\']\s*\)', t))
    validated |= set(re.findall(
        r'registry\s*\.\s*category\(\s*["\']([^"\']+)["\']\s*\)\s*\.\s*addValidation\(', t))
    for a, c in al.items():
        if re.search(rf'\b{re.escape(a)}\s*\.\s*addValidation\(', t):
            validated.add(c)
print(len(validated), len(cats))
PYEOF
)"
# Graph/Pivot VIEWS are eagerly bundled (assets_backend globs views/**); only
# the Chart.js/FullCalendar LIBRARIES are lazy. The docs contradicted
# themselves on this, so pin both the manifest fact and the wording.
assert_eq "assets_backend eagerly globs views/** (graph+pivot are not lazy)" \
    "$(python3 -c "import ast;m=ast.literal_eval(open('$WEB/__manifest__.py').read());print(sum(1 for i in m['assets']['web.assets_backend'] if isinstance(i,str) and 'static/src/views/**' in i))")" "1"
assert_eq "no backend lazy bundle exists" \
    "$(python3 -c "import ast;m=ast.literal_eval(open('$WEB/__manifest__.py').read());print(sum(1 for b in m['assets'] if 'lazy' in b and 'frontend' not in b))")" "0"
assert_eq "ARCHITECTURE.md does not call the graph/pivot views lazy-loaded" \
    "$(grep -cE '^\| (Graph|Pivot) \|.*— lazy loaded' "$DOC/ARCHITECTURE.md")" "0"

assert_eq "CONVENTIONS #11 cites the real registry schema coverage" \
    "$(grep -cE "\*\*${reg_val} of ${reg_tot} web-module categories\*\*" "$DOC/CONVENTIONS.md")" "1"

assert_eq "ARCHITECTURE.md covers every service registered in web" "${svc_undoc:-PARSE_FAILED}" "0"
assert_eq "ARCHITECTURE.md service rows name the real file" "${svc_badpath:-PARSE_FAILED}" "0"
assert_eq "DIRECTORY_MAP.md Files column matches the filesystem on every row" \
    "${dirmap_bad:-PARSE_FAILED}" "0"
assert_eq "DIRECTORY_MAP.md has no stale Lines column" \
    "$(grep -c '^| Directory | Layer | Files | Primary Responsibility |' "$DOC/DIRECTORY_MAP.md")" "1"
assert_eq "DIRECTORY_MAP.md lists no directory that does not exist" "${map_only:-none}" "none"
assert_eq "DIRECTORY_MAP.md omits no directory that does exist" "${disk_only:-none}" "none"
# Cite-fingerprint: confirm the underlying count.
assert_eq "static/src directory entries incl. root (excl. gitignored .claude cruft)" \
    "$((SRC_DIRS + 1))" "238"
assert_eq "polyfills/ directory deleted" \
    "$([ -d "$WEB/static/src/polyfills" ] && echo 1 || echo 0)" "0"
assert_eq "DIRECTORY_MAP.md dropped the polyfills row" \
    "$(grep -c 'polyfills' "$WEB/machine_doc_v1/DIRECTORY_MAP.md")" "0"
assert_eq "DIRECTORY_MAP.md has a core/lib row" \
    "$(grep -cE '^\| .core/lib/. \|' "$WEB/machine_doc_v1/DIRECTORY_MAP.md")" "1"
assert_eq "DIRECTORY_MAP.md has a search/embedded_actions_bar row" \
    "$(grep -cE '^\| .search/embedded_actions_bar/. \|' "$WEB/machine_doc_v1/DIRECTORY_MAP.md")" "1"

# 17. TEST_TAGS.md untagged-files table — the five test files that carry no
#     web_* topic tag, derived from the AST rather than hardcoded here.
untagged=$("$VENV_PY" - "$WEB/tests" <<'PYEOF' 2>/dev/null
import ast, pathlib, sys
n = 0
for p in sorted(pathlib.Path(sys.argv[1]).glob("test_*.py")):
    tags = set()
    for node in ast.walk(ast.parse(p.read_text())):
        if isinstance(node, ast.ClassDef):
            for dec in node.decorator_list:
                if isinstance(dec, ast.Call) and getattr(
                        dec.func, "id", getattr(dec.func, "attr", "")) == "tagged":
                    tags |= {a.value for a in dec.args if isinstance(a, ast.Constant)}
    if not any(str(t).startswith("web_") for t in tags):
        n += 1
print(n)
PYEOF
)
assert_eq "test files with no web_* topic tag" "${untagged:-AST_FAILED}" "5"
assert_eq "TEST_TAGS.md tabulates all five" \
    "$(grep -cE '^\| .test_(fontawesome|pdfjs_dist|ir_asset_scope|js_addons|scss_design_system)\.py. \|' "$WEB/machine_doc_v1/TEST_TAGS.md")" "5"

# 18. ESM pipeline moved to the declarative registry (odoo/tools/assets/):
#     the assetsbundle frozensets (_ESM_APP_BUNDLES / ESM_BUNDLES /
#     DYNAMIC_ESM_BUNDLES / IMPORT_MAP_INCLUDES) are GONE — bundle membership
#     is declared per-module under the manifest 'esm' key and aggregated by
#     esm_registry().  Assert the symbols by existence, not line number
#     (assetsbundle.py is now the assetsbundle/ package; native-node helpers
#     moved to ir_qweb_assets.py).
if skip_missing "$REPO/odoo/tools/assets" "ESM pipeline (esm_registry/esbuild/assetsbundle) assertions" 9; then :; else
PYBASE="$REPO/odoo/addons/base/models"
PYTOOLS="$REPO/odoo/tools/assets"
assert_eq "assetsbundle: hardcoded ESM frozensets are gone" \
    "$(grep -rE '_ESM_APP_BUNDLES|DYNAMIC_ESM_BUNDLES|IMPORT_MAP_INCLUDES = ' "$PYBASE/assetsbundle" | wc -l)" "0"
assert_eq "esm_registry.py exports esm_registry()" \
    "$(grep -c 'def esm_registry' "$PYTOOLS/esm_registry.py")" "1"
assert_eq "esm_registry.py defines the EsmRegistry NamedTuple" \
    "$(grep -c 'class EsmRegistry' "$PYTOOLS/esm_registry.py")" "1"
assert_eq "esm_registry.py defines validate_esm_config" \
    "$(grep -c 'def validate_esm_config' "$PYTOOLS/esm_registry.py")" "1"
assert_eq "esbuild.py defines _LIB_CANDIDATES" \
    "$(grep -cE '_LIB_CANDIDATES: dict' "$PYTOOLS/esbuild.py")" "1"
assert_eq "esm_graph.py defines is_native_module" \
    "$(grep -c 'def is_native_module' "$PYTOOLS/esm_graph.py")" "1"
assert_eq "assetsbundle/bundle.py gates ESM via esm_registry().bundles" \
    "$(grep -c 'esm_registry().bundles' "$PYBASE/assetsbundle/bundle.py")" "1"
assert_eq "assetsbundle/bundle.py defines esbuild_native_bundle" \
    "$(grep -c 'def esbuild_native_bundle' "$PYBASE/assetsbundle/bundle.py")" "1"
assert_eq "ir_qweb_assets.py defines _get_native_module_nodes" \
    "$(grep -cE 'def _get_native_module_nodes\(' "$PYBASE/ir_qweb_assets.py")" "1"
fi
assert_eq "ESM_BUNDLING.md documents the manifest 'esm' key" \
    "$(grep -c 'dynamic_children' "$WEB/machine_doc_v1/ESM_BUNDLING.md")" "4"

# 19. Symbols named in STATE_MANAGEMENT.md "Key files" block. Asserted by
#     refactor, so the docs now name symbols and this harness matches them.
assert_eq "form_controller.js defines save()" \
    "$(grep -cE 'async save\(' "$WEB/static/src/views/form/form_controller.js")" "1"
assert_eq "form_controller.js defines discard()" \
    "$(grep -cE 'async discard\(' "$WEB/static/src/views/form/form_controller.js")" "1"
assert_eq "form_controller.js defines beforeLeave()" \
    "$(grep -cE 'async beforeLeave\(' "$WEB/static/src/views/form/form_controller.js")" "1"
assert_eq "record.js defines _applyChanges()" \
    "$(grep -cE '^    _applyChanges\(' "$WEB/static/src/model/relational_model/record.js")" "1"
assert_eq "record.js defines discard()" \
    "$(grep -cE 'async discard\(' "$WEB/static/src/model/relational_model/record.js")" "1"
# CLEAR-CACHES emission/listener inventory (STATE_MANAGEMENT "emission sites").
assert_eq "invalidator service emits CLEAR_CACHES" \
    "$(grep -c 'CLEAR_CACHES' "$WEB/static/src/services/result_set_cache_invalidator_service.js")" "2"
assert_eq "invalidator service handles lang_install full clear" \
    "$(grep -c 'lang_install' "$WEB/static/src/services/result_set_cache_invalidator_service.js")" "1"
assert_eq "action_cache_invalidation.js emits CLEAR_CACHES" \
    "$(grep -c 'CLEAR_CACHES' "$WEB/static/src/webclient/actions/action_cache_invalidation.js")" "1"
assert_eq "service_worker_service.js emits CLEAR_CACHES on SW hard refresh" \
    "$(grep -c 'CLEAR_CACHES' "$WEB/static/src/webclient/service_worker_service.js")" "1"
assert_eq "rpc.js is the CLEAR_CACHES listener" \
    "$(grep -c 'addEventListener(RpcEvent.CLEAR_CACHES' "$WEB/static/src/core/network/rpc.js")" "1"

# 21. TEST_TAGS.md test counts.
#     Counted through Odoo's own loader, NOT by grepping `def test_`.  The old
#     regex here split the file on `@tagged(...)\nclass` and counted `def test_`
#     until the next tagged class, so it (a) attributed an untagged class's
#     methods to whichever tagged class preceded it and (b) missed every method
#     make_suite() is what `--test-tags` actually selects, so it cannot drift
#     from the runner the way a text pattern can.
count_tag_tests() {
    # $1 = topic tag; emits the number of tests make_suite() collects for it.
    # No database required — collection only.
    local tag="$1"
    (cd "$(dirname "$(dirname "$WEB")")" && "$VENV_PY" - "$tag" "$ODOO_CONF" <<'PY' 2>/dev/null
import sys
tag, conf = sys.argv[1], sys.argv[2]
from odoo.tools import config
config.parse_config(["-c", conf])
config["test_tags"] = tag
from odoo.tests.loader import make_suite
print(len(list(make_suite(["web"], tag))))
PY
    )
}
if ! (cd "$REPO" && "$VENV_PY" -c "import odoo" >/dev/null 2>&1); then
    echo "SKIP: TEST_TAGS make_suite counts — odoo not importable with $VENV_PY"
    SKIP=$((SKIP+14))
else
    for spec in \
        "web_unit:290" \
        "web_http:87" \
        "web_tour:5" \
        "web_js:39" \
        "web_perf:26" \
        "web_benchmark:8" \
        "click_all:2"; do
        tag="${spec%:*}"
        expected="${spec##*:}"
        actual=$(count_tag_tests "$tag")
        assert_eq "TEST_TAGS $tag test count (make_suite)" "${actual:-LOADER_FAILED}" "$expected"
        # And the doc must cite the matching number.
        assert_eq "TEST_TAGS.md cites $expected for $tag" \
            "$(grep -cE "\`$tag\`.*\| $expected tests" "$WEB/machine_doc_v1/TEST_TAGS.md")" "1"
    done
fi

# 20. (removed) JS_FILE_INDEX body-header assertions — JS_FILE_INDEX.md deleted

# 22. CI typecheck gate is a BLOCKING drift-zero ratchet (floor committed in
#     tooling/ratchet/baselines/tsc.json), not the old warn-only annotate job.
if skip_missing "$REPO/.github/workflows/typecheck.yml" "CI typecheck-gate assertions" 6; then :; else
TYPECHECK_YML="$REPO/.github/workflows/typecheck.yml"
assert_eq "typecheck.yml has no continue-on-error key (blocking gate)" \
    "$(grep -c 'continue-on-error:' "$TYPECHECK_YML")" "0"
assert_eq "typecheck.yml enforces via tooling/ratchet" \
    "$(grep -c 'tooling/ratchet/ratchet.py tsc' "$TYPECHECK_YML")" "3"
assert_eq "JSDOC doc: warn-only claim replaced by blocking ratchet" \
    "$(grep -c 'continue-on-error: true' "$WEB/machine_doc_v1/JSDOC_TYPE_TIGHTENING.md")" "0"
# The doc must NOT restate the floor — that duplication is what drifted
# (workflow comment said 2002, doc said 1917, baseline said 2274, truth 2155).
assert_eq "JSDOC doc does not restate the tsc floor" \
    "$(grep -cE '\*\*(1917|2002|2274|2155)\*\* errors' "$WEB/machine_doc_v1/JSDOC_TYPE_TIGHTENING.md")" "0"
assert_eq "typecheck.yml does not restate the tsc floor" \
    "$(grep -cE '^# \(Floor [0-9]+ as of' "$TYPECHECK_YML")" "0"
tsc_floor=$(python3 -c "import json;print(json.load(open('$REPO/tooling/ratchet/baselines/tsc.json'))['count'])" 2>/dev/null || echo "missing")
# The floor must equal what tsc actually reports; a floor above reality makes
# the ratchet exit 1 on "improvement" and leaves mainline red.
assert_eq "committed tsc ratchet floor is a plausible current value" \
    "$([ "$tsc_floor" -gt 0 ] 2>/dev/null && echo ok || echo bad)" "ok"
fi

# 23. Conditional /web/webclient/load_menus (X-Menus-Hash round-trip).
assert_eq "home.py sends X-Menus-Hash" \
    "$(grep -c '"X-Menus-Hash"' "$WEB/controllers/home.py")" "1"
assert_eq "home.py returns empty 304 on hash match" \
    "$(grep -c 'status=304' "$WEB/controllers/home.py")" "1"
assert_eq "menu_service.js echoes the hash back as ?hash=" \
    "$(grep -c '?hash=' "$WEB/static/src/webclient/menus/menu_service.js")" "1"
assert_eq "ROUTE_MAP.md load_menus row documents the conditional fetch" \
    "$(grep -c 'X-Menus-Hash' "$WEB/machine_doc_v1/ROUTE_MAP.md")" "1"
assert_eq "CONVENTIONS gotcha #14 covers the load_menus hash round-trip" \
    "$(grep -c 'X-Menus-Hash' "$WEB/machine_doc_v1/CONVENTIONS.md")" "1"

# 24. useReactiveModel + Model._updateEpoch + reactiveRenderers opt-out.
assert_eq "model.js exports useReactiveModel" \
    "$(grep -c 'export function useReactiveModel' "$WEB/static/src/model/model.js")" "1"
assert_eq "model.js notify() bumps _updateEpoch" \
    "$(grep -c 'this._updateEpoch++' "$WEB/static/src/model/model.js")" "1"
assert_eq "reactiveRenderers opt-out is checked in the model hook" \
    "$(grep -c 'ModelClass).reactiveRenderers' "$WEB/static/src/model/model.js")" "1"
# The pivot and graph RENDERERS subscribe; their models do not (the old
# assertion's label claimed 4 files incl. models, which was never true).
assert_eq "pivot renderer uses useReactiveModel" \
    "$(grep -c 'useReactiveModel(this.props.model)' "$WEB/static/src/views/pivot/pivot_renderer.js")" "1"
assert_eq "graph renderer uses useReactiveModel" \
    "$(grep -c 'useReactiveModel(this.props.model)' "$WEB/static/src/views/graph/graph_renderer.js")" "1"
assert_eq "STATE_MANAGEMENT documents useReactiveModel" \
    "$(grep -c 'useReactiveModel' "$WEB/machine_doc_v1/STATE_MANAGEMENT.md")" "2"

# 25. _updateConfig was renamed to _patchConfig / _reloadWithConfig — docs must
#     not cite the old name.
assert_eq "no _updateConfig left in model/" \
    "$(grep -rc '_updateConfig' "$WEB/static/src/model" --include='*.js' 2>/dev/null | awk -F: '{s+=$NF} END {print s+0}')" "0"
assert_eq "docs do not cite _updateConfig" \
    "$(grep -rc '_updateConfig' "$WEB/machine_doc_v1"/*.md "$WEB/doc"/*.md 2>/dev/null | awk -F: '{s+=$NF} END {print s+0}')" "0"

# 26. ListRecordRow extraction (per-row component, renderer-delegation contract).
assert_eq "list_record_row.js exports ListRecordRow" \
    "$(grep -c 'export class ListRecordRow extends Component' "$WEB/static/src/views/list/list_record_row.js")" "1"
assert_eq "row body template keeps its historical t-name (compat contract)" \
    "$(grep -rc 'web.ListRenderer.RecordRow' "$WEB/static/src/views/list/list_renderer.xml" 2>/dev/null | awk -F: '{s+=$NF} END {print s+0}')" "1"
assert_eq "CONVENTIONS gotcha #15 covers ListRecordRow" \
    "$(grep -c 'ListRecordRow' "$WEB/machine_doc_v1/CONVENTIONS.md")" "1"

# 27. Scoped re-validation dep-maps.
assert_eq "record_utils.js exports computeRevalidationScope" \
    "$(grep -c 'export function computeRevalidationScope' "$WEB/static/src/model/relational_model/record_utils.js")" "1"
assert_eq "record.js passes scopedFields to the removeInvalidOnly re-check" \
    "$(grep -c 'removeInvalidOnly: true, scopedFields' "$WEB/static/src/model/relational_model/record.js")" "1"
assert_eq "STATE_MANAGEMENT documents computeRevalidationScope" \
    "$(grep -c 'computeRevalidationScope' "$WEB/machine_doc_v1/STATE_MANAGEMENT.md")" "1"

# 28. Kanban progress bars: local drag-move reconcile.
assert_eq "progress_bar_hook has registerRecordMove" \
    "$(grep -c 'registerRecordMove(recordId, sourceGroupId, targetGroupId)' "$WEB/static/src/views/kanban/progress_bar_hook.js")" "1"
assert_eq "progress_bar_hook has _reconcileMove (JSDoc + definition)" \
    "$(grep -c '_reconcileMove(record, move)' "$WEB/static/src/views/kanban/progress_bar_hook.js")" "2"
assert_eq "CONVENTIONS gotcha #16 covers the local reconcile" \
    "$(grep -c '_reconcileMove' "$WEB/machine_doc_v1/CONVENTIONS.md")" "1"

# 29. SearchModelEvent enum (typed events table row must match the export).
# Typed-events table: every constant in core/events.js must be documented with
# its real string value. 14 of 33 were missing while the table still "passed"
# a cardinality check on one group.
read -r ev_undoc ev_badval <<<"$("$VENV_PY" - "$WEB" <<'PYEOF' 2>/dev/null
import re, pathlib, sys
web = pathlib.Path(sys.argv[1])
src = (web / "static/src/core/events.js").read_text()
truth = {}
for gm in re.finditer(r"export const (\w+) = Object\.freeze\(\{(.*?)\}\);", src, re.S):
    for m in re.finditer(r'(\w+):\s*"([^"]+)"', gm.group(2)):
        truth[f"{gm.group(1)}.{m.group(1)}"] = m.group(2)
doc = (web / "machine_doc_v1/STATE_MANAGEMENT.md").read_text()
documented = {}
for m in re.finditer(
        r"^\| `(\w+)\.(\w+)`(?: / `?(\w+)`?)* \| `([^`]+)`(?: / `([^`]+)`)*(?: / `([^`]+)`)* \|",
        doc, re.M):
    grp = m.group(1)
    names = [g for g in (m.group(2), m.group(3)) if g]
    vals = [g for g in (m.group(4), m.group(5), m.group(6)) if g]
    for i, n in enumerate(names):
        documented[f"{grp}.{n}"] = vals[i] if i < len(vals) else vals[0]
# groups documented as a single slash row (ADDED / LOADED / ERROR)
for m in re.finditer(r"^\| `(\w+)\.(\w+)` / `(\w+)` / `(\w+)` \| `([^`]+)` / `([^`]+)` / `([^`]+)` \|", doc, re.M):
    g = m.group(1)
    for n, v in zip(m.group(2, 3, 4), m.group(5, 6, 7)):
        documented[f"{g}.{n}"] = v
undoc = [k for k in truth if k not in documented]
badval = [k for k in documented if k in truth and documented[k] != truth[k]]
print(len(undoc), len(badval))
PYEOF
)"
assert_eq "STATE_MANAGEMENT documents every core/events.js constant" "${ev_undoc:-PARSE_FAILED}" "0"
assert_eq "STATE_MANAGEMENT event string values are correct" "${ev_badval:-PARSE_FAILED}" "0"

assert_eq "core/events.js exports SearchModelEvent" \
    "$(grep -c 'export const SearchModelEvent' "$WEB/static/src/core/events.js")" "1"
assert_eq "STATE_MANAGEMENT typed-events table has the 4 SearchModelEvent rows" \
    "$(grep -c 'SearchModelEvent\.' "$WEB/machine_doc_v1/STATE_MANAGEMENT.md")" "4"

# 30. rpc_cache 'immutable' option — deep-frozen shared payloads, adopted by
#     field_service's fields_get disk cache.
assert_eq "rpc_cache.js implements the immutable option (deepFreeze)" \
    "$(grep -c 'immutable ? deepFreeze : deepCopy' "$WEB/static/src/core/network/rpc_cache.js")" "1"
assert_eq "field_service uses cache({type:'disk', immutable:true})" \
    "$(grep -c 'immutable: true' "$WEB/static/src/services/field_service.js")" "1"

# 31. EmbeddedActionsBar extracted out of ControlPanel.
assert_eq "embedded_actions_bar component exists" \
    "$([ -f "$WEB/static/src/search/embedded_actions_bar/embedded_actions_bar.js" ] && echo 1 || echo 0)" "1"

# 31b. ROUTE_MAP totals + removed QUnit runner route.
assert_eq "webclient.py no longer serves /web/tests/legacy" \
    "$(grep -c '/web/tests/legacy' "$WEB/controllers/webclient.py")" "0"
# AST-count route-decorated FUNCTIONS. The old raw `grep -c @route` counted
# One handler carries two @route decorators, so counting decorator occurrences
# over-reports handlers by one; count decorated FUNCTIONS instead. URLs are the
# distinct route strings those decorators declare (verified against the live
# werkzeug routing map: all 108 resolve).
read -r ROUTE_HANDLERS ROUTE_URLS <<<"$(python3 - "$WEB/controllers" <<'PYEOF'
import ast, pathlib, sys
n = 0; urls = set()
for f in sorted(pathlib.Path(sys.argv[1]).glob("*.py")):
    for node in ast.walk(ast.parse(f.read_text())):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            hit = False
            for dec in node.decorator_list:
                if isinstance(dec, ast.Call) and getattr(
                        dec.func, "attr", getattr(dec.func, "id", "")) == "route":
                    hit = True
                    for a in dec.args:
                        if isinstance(a, ast.Constant):
                            urls.add(a.value)
                        elif isinstance(a, (ast.List, ast.Tuple)):
                            urls |= {e.value for e in a.elts if isinstance(e, ast.Constant)}
            if hit:
                n += 1
print(n, len(urls))
PYEOF
)"
# The per-category rows must SUM to the AST truth. Cardinality-only checking is
# what let the openapi row go missing while the total still read 75.
route_sum=$("$VENV_PY" - "$DOC/ROUTE_MAP.md" <<'PYEOF' 2>/dev/null
import re, sys
h = u = 0
for ln in open(sys.argv[1]):
    m = re.match(r"\|\s*([^|]+?)\s*\|\s*(\d+)\s*/\s*(\d+)\s*\|", ln)
    if m and "Total" not in m.group(1):
        h += int(m.group(2)); u += int(m.group(3))
print(f"{h}/{u}")
PYEOF
)
assert_eq "ROUTE_MAP category rows sum to the handler/URL truth" \
    "${route_sum:-PARSE_FAILED}" "$ROUTE_HANDLERS/$ROUTE_URLS"
assert_doc_cites "ROUTE_MAP total row cites the handler count" "$ROUTE_HANDLERS" \
    '\\*\\*%s handlers' ROUTE_MAP.md

# 32. ADR index (core-root doc/adr) lists ADR-0011.
if skip_missing "$REPO/doc/adr/README.md" "ADR index assertion" 1; then :; else
assert_eq "doc/adr/README.md indexes ADR-0011" \
    "$(grep -c '0011-persistence-backend-port' "$REPO/doc/adr/README.md" 2>/dev/null || echo 0)" "1"
fi

echo ""
echo "================================================================"
echo "TOTAL: $PASS passed, $FAIL failed, $SKIP skipped"
echo "================================================================"
exit $FAIL
