#!/bin/bash
# Web module architecture fact-check (round 6 — 2026-07-10 path + de-pin reconcile)
# Run from any cwd. Read-only. CI-safe.
# Round 6 highlights: workspace path moved addons/core → addons/odoo; symbol
# citations de-pinned from line numbers (they drifted 20-50 lines per refactor)
# to existence checks; assetsbundle.py split into the assetsbundle/ package and
# native-node helpers moved to ir_qweb_assets.py; test-file/sendBeacon counts
# refreshed to current reality.
# Round 5 highlights: declarative esm_registry (manifest 'esm' key) replaced the
# assetsbundle frozensets; known_values field-scoped optimistic locking replaced
# last_write_date; chartjs/fullcalendar lazy ESM loaders replaced the lib
# bundles; legacy QUnit chain fully removed; View Transitions removed;
# load_coordinator removed; useReactiveModel/ListRecordRow/EmbeddedActionsBar/
# conditional load_menus added.

set -u
WEB="/home/marin/Odoo/addons/odoo/addons/web"
PASS=0
FAIL=0

assert_eq() {
    local name="$1" actual="$2" expected="$3"
    if [ "$actual" = "$expected" ]; then
        echo "PASS: $name [$actual]"; PASS=$((PASS+1))
    else
        echo "FAIL: $name — expected [$expected] got [$actual]"; FAIL=$((FAIL+1))
    fi
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
# 658 (2026-07-03 machinery wave): +1 over the 657 round-5 baseline
# (core/errors/stack_frames.js — native stack parsing + sourcemap consumer
# replacing vendored stacktracejs).  Round-5 note: 657 was +8 over the 649
# round-4 baseline from this
# audit wave (core/lib/{chartjs,fullcalendar}.js, search/embedded_actions_bar,
# views/list/list_record_row.js, model/relational_model split files, ...)
# minus the deleted polyfills/ file and load_coordinator.js.
assert_eq "JS file count" "$(find "$WEB/static/src" -name "*.js" -type f | wc -l)" "658"

# ------- Type coverage -------
# 656 = 658 total - 2 intentional exclusions (module_loader + service_worker)
assert_eq "@ts-check coverage" \
    "$(grep -rl "@ts-check" "$WEB/static/src" --include="*.js" 2>/dev/null | wc -l)" "656"
assert_eq "Untyped JS files (intentional: module_loader + service_worker)" \
    "$(find "$WEB/static/src" -name "*.js" -type f -exec grep -L "@ts-check" {} + 2>/dev/null | wc -l)" "2"

# ------- Test scope -------
assert_eq "Hoot test files" "$(find "$WEB/static/tests" -name "*.test.js" 2>/dev/null | wc -l)" "378"
# Legacy QUnit chain REMOVED (see TEST_TAGS.md): static/tests/legacy/ tree,
# vendored static/lib/qunit/, the web.tests_assets / web.__assets_tests_call__ /
# web.qunit_suite_tests bundles and the /web/tests/legacy route are all gone.
# The two production-relevant suites were ported to HOOT under tests/legacy_js/.
assert_eq "Legacy QUnit tree deleted (static/tests/legacy)" \
    "$([ -d "$WEB/static/tests/legacy" ] && echo 1 || echo 0)" "0"
assert_eq "Vendored QUnit deleted (static/lib/qunit)" \
    "$([ -d "$WEB/static/lib/qunit" ] && echo 1 || echo 0)" "0"
assert_eq "No qunit bundles left in manifest" \
    "$(grep -c "qunit" "$WEB/__manifest__.py")" "0"
# One historical comment in module_set.hoot.js still says the word "QUnit.";
# no executable QUnit API usage remains.
assert_eq "No QUnit. references remain (legacy chain fully removed)" \
    "$(grep -rl "QUnit\." "$WEB/static/tests" --include="*.js" 2>/dev/null | wc -l)" "0"
assert_eq "No QUnit.test/QUnit.module calls anywhere in static/" \
    "$(grep -rE "QUnit\.(test|module)\(" "$WEB/static" --include="*.js" 2>/dev/null | wc -l)" "0"
assert_eq "Ported legacy suites live in tests/legacy_js" \
    "$(find "$WEB/static/tests/legacy_js" -name "*.test.js" 2>/dev/null | wc -l)" "3"

# ------- Reactivity migration progress -------
# Sharpened from round-1: count actual class declarations, not file matches.
# File-count grep over-counts because reactive.js itself matches via docstring.
REACTIVE_PATTERN='^(\s*export\s+)?class\s+\w+\s+extends\s+Reactive\b'
SIGNALSTORE_PATTERN='^(\s*export\s+)?class\s+\w+\s+extends\s+SignalStore\b'

# Helper: count declarations in production code only (exclude tests + machine_doc + .md).
count_prod_decls() {
    local pattern="$1"
    local files
    files=$(grep -rEl "$pattern" /home/marin/Odoo/addons/ 2>/dev/null \
        | grep -v "machine_doc\|\.test\.js\|\.md$")
    if [ -z "$files" ]; then
        echo 0
    else
        echo "$files" | xargs grep -Ec "$pattern" \
            | awk -F: '{ s += $NF } END { print s+0 }'
    fi
}
reactive_prod=$(count_prod_decls "$REACTIVE_PATTERN")
# Round 2 — full migration complete 2026-05-02:
#   17 sites in batch 1 (web 2 + core 10 + enterprise 5).
#   5 sites in batch 2 (web_studio: view_editor_model, edition_flow×3, report_editor_model)
#       — required deleting web_studio's parallel Reactive class at
#         enterprise/web_studio/static/src/client_action/utils.js:75-86 and replacing
#         8 .raw() callers with toRaw(this) from @odoo/owl in edition_flow.js.
#   Total: 22 of 22 production sites on SignalStore. 0 remaining on Reactive alias.
#   Round 3 (2026-05-09): +1 = 23 total.  FormSaveCoordinator was added at
#   form_save_coordinator.js:60 to own the form save lifecycle (replacing
#   the historical positional-boolean onSaveError pattern documented in
#   CONVENTIONS.md gotcha #12).  It extends SignalStore so its `status`
#   and `lastError` fields are observable from external readers.
#   Round 5 (2026-07-02): 27 → 26. RelationalModelLoadCoordinator was deleted
#   as dead code (commit b906a0295d6 — nothing ever read its status); the load
#   axis is keepLast + the reactive model.isReady flag.
assert_eq "Reactive class declarations (production)" "$reactive_prod" "0"

reactive_web=$(grep -rEln "$REACTIVE_PATTERN" "$WEB/static/src" 2>/dev/null | wc -l)
assert_eq "Reactive class declarations in core/addons/web" "$reactive_web" "0"

signalstore=$(count_prod_decls "$SIGNALSTORE_PATTERN")
assert_eq "SignalStore class declarations (production code)" "$signalstore" "26"
assert_eq "load_coordinator.js stays deleted" \
    "$([ -f "$WEB/static/src/model/relational_model/load_coordinator.js" ] && echo 1 || echo 0)" "0"
assert_eq "STATE_MANAGEMENT.md records the load-coordinator removal" \
    "$(grep -c 'RelationalModelLoadCoordinator. was REMOVED' "$WEB/machine_doc_v1/STATE_MANAGEMENT.md")" "1"

# Verify web_studio's parallel Reactive class is gone — replaced by SignalStore + toRaw().
web_studio_reactive_class=$(grep -c "^export class Reactive {" \
    /home/marin/Odoo/addons/enterprise/web_studio/static/src/client_action/utils.js 2>/dev/null)
assert_eq "web_studio's parallel Reactive class (deleted)" "$web_studio_reactive_class" "0"

# Verify the .raw() callers were correctly migrated to toRaw(this).
web_studio_raw_calls=$(grep -rc "\.raw()" /home/marin/Odoo/addons/enterprise/web_studio/static/src 2>/dev/null \
    | awk -F: '{ s += $NF } END { print s+0 }')
assert_eq "web_studio .raw() callers (replaced by toRaw(this))" "$web_studio_raw_calls" "0"

# ------- RUM Phase 1 — landed 2026-05-02 -------
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
assert_eq "MODEL_MAP.md inp row documents the P100 running max" \
    "$(grep -c 'worst-observed interaction duration' "$WEB/machine_doc_v1/MODEL_MAP.md")" "1"

# sendBeacon usages: 10 files. Inventory:
#   1. record_save.js              — actual sendBeacon() call (data persistence)
#   2. web_vitals_service.js       — CWV telemetry on pagehide (RUM)
#   3. form_save_coordinator.js    — coordinator's requestUrgentSave() entry point
#   4. form_controller.js          — controller delegates to the coordinator
#   5. relational_model.js         — model-level urgent-save plumbing
#   6. record.js                   — record-level urgent-save fast paths
#   7. core/events.js              — WILL_SAVE_URGENTLY event doc references
#   8. core/errors/error_beacon.js — error telemetry beacon
#   9. module_loader.js            — loader shim beacon plumbing
#  10. fields/input_field_hook.js  — urgent-save comment on input commit
# Only #1, #2, #8 and #9 actually invoke navigator.sendBeacon().
sendbeacon_files=$(grep -rln "sendBeacon" "$WEB/static/src" 2>/dev/null | wc -l)
assert_eq "sendBeacon usages (record_save + web_vitals + error_beacon + urgent-save chain)" "$sendbeacon_files" "10"

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
assert_eq "_gc_old_metrics retention method" "$cwv_gc_method" "2"
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

# ------- CSS custom properties (CORRECTED — they DO exist) -------
css_decls=$(grep -rh "^\s*--[a-zA-Z]" "$WEB/static/src" --include="*.scss" 2>/dev/null | wc -l)
assert_range "CSS custom property declarations" "$css_decls" 300 400
css_uses=$(grep -rh "var(--" "$WEB/static/src" --include="*.scss" 2>/dev/null | wc -l)
assert_range "var(--*) usages" "$css_uses" 350 450

# ------- Coupling: form_controller imports (CORRECTED 8→7) -------
assert_eq "form_controller distinct top-level dirs" \
    "$(grep "^import" "$WEB/static/src/views/form/form_controller.js" \
        | grep -oE "@web/[a-z_]+" | sort -u | wc -l)" "7"

# ------- legacy/js inventory -------
assert_eq "legacy/js JS file count" \
    "$(find "$WEB/static/src/legacy" -name "*.js" -type f 2>/dev/null | wc -l)" "6"

# ------- i18n: plural support (Phase 1, JS-only — 2026-05-10) -------
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
assert_eq "formatX2many migrated to _pl (was 0/1/N if-else)" \
    "$(grep -c "_pl(count, {" "$WEB/static/src/fields/formatters.js")" "1"
# Cite-fingerprint: docstring example shape — the canonical CLDR categories
# {zero, one, two, few, many, other} should appear in the helper's docstring
# so future readers see the full shape, even when call sites only use one/other.
assert_eq "_pl docstring lists all six CLDR plural categories" \
    "$(grep -cE 'zero.*one.*two.*few.*many.*other' "$WEB/static/src/core/l10n/translation.js")" "1"

# ------- OWL bundle (CORRECTED 2.5.3 → 2.8.2) -------
assert_eq "OWL bundle bytes" "$(stat -c '%s' "$WEB/static/lib/owl/owl.js")" "259356"
assert_eq "OWL version string" \
    "$(grep -oE 'version = "[0-9]+\.[0-9]+\.[0-9]+"' "$WEB/static/lib/owl/owl.js" | head -1)" \
    'version = "2.8.2"'

# ------- Service worker -------
assert_range "STALE_WHILE_REVALIDATE_RE refs in SW" \
    "$(grep -c "STALE_WHILE_REVALIDATE_RE" "$WEB/static/src/service_worker.js")" 2 3

# ------- Security: XSS surface (NEW assertions) -------
assert_eq ".innerHTML = usages (both gated by isMarkup check)" \
    "$(grep -rh "\.innerHTML\s*=" "$WEB/static/src" --include="*.js" 2>/dev/null | wc -l)" "2"
assert_eq ".outerHTML = usages" \
    "$(grep -rh "\.outerHTML\s*=" "$WEB/static/src" --include="*.js" 2>/dev/null | wc -l)" "0"
assert_eq "eval()/new Function() usages" \
    "$(grep -rE "\beval\(|new Function\(" "$WEB/static/src" --include="*.js" 2>/dev/null | wc -l)" "0"
assert_eq "markup() trust-hatch import sites" \
    "$(grep -rln "{ markup" "$WEB/static/src" --include="*.js" 2>/dev/null | wc -l)" "9"

# ------- View Transitions REMOVED (2026-07-02 audit wave) -------
# The G3 startViewTransition wrap was removed from action_container.js; only
# an explanatory comment remains (it explains why the API can't wrap OWL's
# render directly).  Lock the removal so the feature doesn't half-return
# without docs/factcheck being updated.
assert_eq "ActionContainer no longer calls document.startViewTransition" \
    "$(grep -cE 'document\.startViewTransition\(' "$WEB/static/src/webclient/actions/action_container.js")" "0"
assert_eq "No startViewTransition call anywhere in static/src" \
    "$(grep -rE 'startViewTransition\(' "$WEB/static/src" --include="*.js" 2>/dev/null | wc -l)" "0"

# ------- patch() architecture (G14, 2026-05-08) -------
# Convention enforced via CONVENTIONS.md gotcha #13 (prototype-only patching
# for classes, plain-object patching for env/services; never patch a frozen
# ES-module namespace).  No factcheck assertion: a coarse "files combining
# import * as with patch()" grep produced 44 false positives (mostly test
# files where the two patterns are used independently).  The right
# enforcement is the doc + the historical memory of the March 2026 failed
# ESM migration (research/2026-03-12-esm-native-migration-feasibility.md),
# not a regex.

# ------- ORM proxy contract (G5, 2026-05-08) -------
# orm.retry() default must match the documented boot-path budget in CONVENTIONS.md
# (retry: 1).  Pre-G5 the source defaulted to 3, drifting from documented intent.
# A bare orm.retry().call(...) silently got 3 retries against the rationale of
# "cap user-perceived delay at one backoff interval ~200ms".
assert_eq "orm.retry() default value [1]" \
    "$(grep -c 'retry(options = 1)' "$WEB/static/src/services/orm_service.js")" "1"
assert_eq "orm.retry() does NOT default to 3" \
    "$(grep -c 'retry(options = 3)' "$WEB/static/src/services/orm_service.js")" "0"

# ------- Production bundle sizes (NEW — from DB ir_attachment) -------
if psql -d marin190 -c "SELECT 1" >/dev/null 2>&1; then
    main_js=$(psql -d marin190 -At -c \
        "SELECT file_size FROM ir_attachment WHERE name LIKE '%web.assets_web.min.js%' AND file_size IS NOT NULL ORDER BY id DESC LIMIT 1" 2>/dev/null)
    if [ -n "$main_js" ]; then
        # Main backend JS: 384 KB (393194 bytes) — assert within 300-500 KB sanity range
        assert_range "Main backend JS size (web.assets_web.min.js, bytes)" "$main_js" 300000 500000
    fi
    main_css=$(psql -d marin190 -At -c \
        "SELECT file_size FROM ir_attachment WHERE name LIKE '%web.assets_web.min.css%' AND file_size IS NOT NULL ORDER BY id DESC LIMIT 1" 2>/dev/null)
    if [ -n "$main_css" ]; then
        # Main backend CSS: 1.13 MB — much larger than JS
        assert_range "Main backend CSS size (web.assets_web.min.css, bytes)" "$main_css" 900000 1300000
    fi
else
    echo "SKIP: bundle size assertions (DB marin190 unavailable)"
fi

# ------- Doc consistency (cite-fingerprint assertions, added 2026-05-09) -------
# Each pair locks both directions: the new wording must be present AND the
# stale wording must be gone.  This catches the failure mode where a fix
# lands in code but the cited doc keeps describing the old behavior — the
# 2026-05-09 audit found three such drifts that survived for weeks.
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
assert_eq "record_save.js builds the concurrencyBaseline map" \
    "$(grep -c 'const concurrencyBaseline = {}' "$WEB/static/src/model/relational_model/record_save.js")" "1"
assert_eq "record_save.js sends known_values on BOTH paths (urgent + normal)" \
    "$(grep -c 'known_values' "$WEB/static/src/model/relational_model/record_save.js")" "2"
assert_eq "record_save.js no longer sends last_write_date" \
    "$(grep -c 'last_write_date' "$WEB/static/src/model/relational_model/record_save.js")" "0"
assert_eq "server: web_read.py implements _check_concurrent_field_changes" \
    "$(grep -c 'def _check_concurrent_field_changes' "$WEB/models/web_read.py")" "1"
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

# 3. ARCHITECTURE.md JS file counts — sites previously cited 615/621/649;
#    now 657 after the 2026-07-02 audit wave.
assert_eq "ARCHITECTURE.md no stale JS file counts (615/621/649/657)" \
    "$(grep -cE '(615|621|649|657) (JavaScript|JS)' "$WEB/machine_doc_v1/ARCHITECTURE.md")" "0"
assert_eq "ARCHITECTURE.md JS count cited in prose" \
    "$(grep -cE '658 (JavaScript|JS)' "$WEB/machine_doc_v1/ARCHITECTURE.md")" "1"
# (The other site is in a markdown table cell `| JavaScript (src) | 657 |` —
# pattern above won't match because of the pipe layout, so check it separately.)
assert_eq "ARCHITECTURE.md JS table cell" \
    "$(grep -cE '\| JavaScript \(src\) \| 658 \|' "$WEB/machine_doc_v1/ARCHITECTURE.md")" "1"

# 4. Pattern 4 inventory — STATE_MANAGEMENT.md should enumerate verified sites
#    rather than implying an open population.
assert_eq "STATE_MANAGEMENT lists Pattern 4 sites table" \
    "$(grep -c 'Pattern 4 sites' "$WEB/machine_doc_v1/STATE_MANAGEMENT.md")" "1"

# 5. Reactive BC alias dropped 2026-05-09.  After the drop:
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
assert_eq "eslint.config.mjs no longer carries the Reactive-import rule" \
    "$(grep -c "imported.name='Reactive'" /home/marin/Odoo/addons/odoo/eslint.config.mjs)" "0"

# 6. Per-section JS file counts — reality checks against the filesystem.
#    (Top-line total is covered by "JS file count" above.  The former
#    JS_FILE_INDEX.md per-file index was deleted 2026-06-02 — redundant with
#    DIRECTORY_MAP.md's per-directory map.)
# Per-section actual subtotals — three drifted (views, model, services) and
# the others held.  Lock all eight so future drift trips on commit.
for section_check in \
    "components/:74" \
    "core/:111" \
    "fields/:112" \
    "views/:151" \
    "webclient/:56" \
    "model/:42" \
    "services/:37" \
    "ui/:19" \
    "search/:32" \
    "legacy/:6" \
    "libs/:1"; do
    section="${section_check%:*}"
    expected="${section_check##*:}"
    actual=$(find "$WEB/static/src/$section" -name "*.js" -type f 2>/dev/null | wc -l)
    assert_eq "static/src/$section JS count" \
        "$actual" "$expected"
done

# 7. Gotcha #10 cite-fingerprint: archiveEnabled consolidated into
#    view_utils.computeArchiveEnabled(readonlySource, presenceSource).
#    Form gates presence on model.root.activeFields; multi-record passes
#    only props.fields.  The x_active fallback now lives in the shared
#    helper, not in form_controller.
assert_eq "view_utils exports computeArchiveEnabled(readonlySource, presenceSource)" \
    "$(grep -c 'export function computeArchiveEnabled(readonlySource, presenceSource = readonlySource)' "$WEB/static/src/views/view_utils.js")" "1"
assert_eq "computeArchiveEnabled has the x_active fallback" \
    "$(grep -cE '"x_active" in presenceSource' "$WEB/static/src/views/view_utils.js")" "1"
assert_eq "form_controller has archiveEnabled getter" \
    "$(grep -c 'get archiveEnabled()' "$WEB/static/src/views/form/form_controller.js")" "1"
assert_eq "form_controller delegates with the activeFields presence gate" \
    "$(grep -c 'computeArchiveEnabled(this.props.fields, this.model.root.activeFields)' "$WEB/static/src/views/form/form_controller.js")" "1"
assert_eq "multi_record_controller delegates to computeArchiveEnabled" \
    "$(grep -c 'computeArchiveEnabled(this.props.fields)' "$WEB/static/src/views/multi_record_controller.js")" "1"
assert_eq "CONVENTIONS gotcha #10 names the computeArchiveEnabled form call" \
    "$(grep -c 'computeArchiveEnabled(this.props.fields, this.model.root.activeFields)' "$WEB/machine_doc_v1/CONVENTIONS.md")" "1"
assert_eq "CONVENTIONS gotcha #10 carries no stale form_controller.js line cites" \
    "$(grep -cE 'form_controller.js:[0-9]' "$WEB/machine_doc_v1/CONVENTIONS.md")" "0"

# 8. Gotcha #5 cite-fingerprint: /web/image route count (claim: 17 patterns).
assert_eq "binary.py /web/image route mentions match doc claim (17)" \
    "$(grep -cE '/web/image' "$WEB/controllers/binary.py")" "17"

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
# Cite-fingerprint: kanban_controller.js:163 is the *canonical exception* to
# Pattern 4 — the setter must clear sample data on the same microtask as
# the groupId mutation; a useEffect rewrite was reverted (commit 19fb5d01bb81)
# because deferred cleanup breaks 3 sample-data integration tests.  Lock
# both the setter line AND the rationale comment so the next person who
# decides to "clean this up" trips a CI assertion.
assert_eq "kanban_controller.js groupId setter (canonical Pattern 4 exception)" \
    "$(grep -c 'set groupId(groupId)' "$WEB/static/src/views/kanban/kanban_controller.js")" "1"
assert_eq "kanban_controller.js timing-contract rationale comment present" \
    "$(grep -c 'synchronous timing contract' "$WEB/static/src/views/kanban/kanban_controller.js")" "1"
assert_eq "kanban_controller.js cites reverted migration commit" \
    "$(grep -c '19fb5d01bb81' "$WEB/static/src/views/kanban/kanban_controller.js")" "1"

# 10. Registry typing: dead `effetcs` key removed (typo fix, 2026-05-10).
#     The `GlobalRegistryCategories` interface in @types/registries/registries.d.ts
#     historically declared both `effetcs: EffectsRegistryItemShape` (typo) and
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
# contained the typo — historical artifacts, not live code).
assert_eq "no 'effetcs' consumers across active repos" \
    "$(grep -rln "effetcs" \
        /home/marin/Odoo/addons/odoo \
        /home/marin/Odoo/addons/enterprise \
        /home/marin/Odoo/addons/agromarin \
        --exclude-dir=machine_doc_v1 \
        --exclude-dir=.git 2>/dev/null | wc -l)" "0"

# ------- Round 4 (2026-05-19): assertions for fixes the audit applied -------
# Each fix from the 2026-05-19 audit pass gets a cite-fingerprint here so the
# fix stays in lockstep with code.  Catches the failure mode "doc was updated
# but the code subsequently shifted underneath it".

# 11. dedup proxy on ORM — ARCHITECTURE.md must document it; rpc.js must
#     accept it in RPC_SETTINGS.  Both are 2026-05-09 additions that were
#     missing from ARCHITECTURE.md until 2026-05-19.
assert_eq "orm_service.js exports 'get dedup' proxy" \
    "$(grep -cE '^\s+get dedup\(\)' "$WEB/static/src/services/orm_service.js")" "1"
# RPC_SETTINGS is a multi-line Set literal; match the "dedup" member directly.
assert_eq "rpc.js RPC_SETTINGS whitelist includes 'dedup'" \
    "$(grep -cE '^\s*"dedup",' "$WEB/static/src/core/network/rpc.js")" "1"
assert_eq "ARCHITECTURE.md documents orm.dedup proxy" \
    "$(grep -cE '\*\*`orm\.dedup`\*\*' "$WEB/machine_doc_v1/ARCHITECTURE.md")" "1"
assert_eq "ARCHITECTURE.md rpc.js whitelist mentions all 6 keys" \
    "$(grep -cE 'cache, silent, headers, timeout, retry, dedup' "$WEB/machine_doc_v1/ARCHITECTURE.md")" "1"

# 12. fullcalendar version — the vendored bundle is now the final v7.0.0
#     (was 7.0.0-rc.3 in round 4; before that the table said 6.1.20).  Lock
#     the table to 7.0.0 and ban both stale cites.
assert_eq "ARCHITECTURE.md fullcalendar row says 7.0.0" \
    "$(grep -cE '\| .fullcalendar. \| 7\.0\.0 \|' "$WEB/machine_doc_v1/ARCHITECTURE.md")" "1"
assert_eq "ARCHITECTURE.md no stale fullcalendar 6.1.20 / 7.0.0-rc.3" \
    "$(grep -cE 'fullcalendar.{0,30}(6\.1\.20|7\.0\.0-rc)' "$WEB/machine_doc_v1/ARCHITECTURE.md")" "0"
assert_eq "fullcalendar vendored bundle is v7 (final 7.0.0 present in source)" \
    "$(grep -c 'FullCalendar v7' "$WEB/static/lib/fullcalendar/fullcalendar.esm.js"):$(grep -m1 -coE 'v7\.0\.0' "$WEB/static/lib/fullcalendar/fullcalendar.esm.js")" "1:1"

# 13. STATE_MANAGEMENT.md phantom AppEvent.FORM_DIALOG_* events removed.
#     The 2026-05-09 service refactor replaced bus indirection with direct
#     push()/pop() calls; the constants no longer exist in core/events.js.
#     The doc was correctly updated 2026-05-19 — lock the deletion.
assert_eq "STATE_MANAGEMENT.md no phantom FORM_DIALOG_ADD row" \
    "$(grep -c 'AppEvent.FORM_DIALOG_ADD' "$WEB/machine_doc_v1/STATE_MANAGEMENT.md")" "0"
assert_eq "STATE_MANAGEMENT.md no phantom FORM_DIALOG_REMOVE row" \
    "$(grep -c 'AppEvent.FORM_DIALOG_REMOVE' "$WEB/machine_doc_v1/STATE_MANAGEMENT.md")" "0"
assert_eq "core/events.js does not export FORM_DIALOG_ADD" \
    "$(grep -cE 'FORM_DIALOG_ADD\s*:' "$WEB/static/src/core/events.js")" "0"

# 14. ARCHITECTURE.md table counts — numeric claims locked.  Catches the
#     drift pattern that motivated this audit (counts grew, doc lagged).
assert_eq "ARCHITECTURE.md File Counts: Python tests = 44" \
    "$(grep -cE '\| Python \(tests\) \| 44 \|' "$WEB/machine_doc_v1/ARCHITECTURE.md")" "1"
assert_eq "Python test file count = 44 (reality check)" \
    "$(find "$WEB/tests" -name "test_*.py" | wc -l)" "44"
assert_eq "ARCHITECTURE.md File Counts: JS tests = 434/378" \
    "$(grep -cE '\| JavaScript \(tests\) \| 434 \(incl\. 378' "$WEB/machine_doc_v1/ARCHITECTURE.md")" "1"
assert_eq "static/tests JS file count = 434 (reality check)" \
    "$(find "$WEB/static/tests" -name "*.js" | wc -l)" "434"
assert_eq "ARCHITECTURE.md File Counts: vendored libs = 91" \
    "$(grep -cE '\| JavaScript \(vendored libs\) \| 91 \|' "$WEB/machine_doc_v1/ARCHITECTURE.md")" "1"
assert_eq "static/lib JS file count = 91 (reality check)" \
    "$(find "$WEB/static/lib" -name "*.js" -type f | wc -l)" "91"

# 15. ARCHITECTURE.md JavaScript Architecture table — lock the Layer subtotals.
#     These mirror the per-section filesystem assertions but for the
#     ARCHITECTURE doc's view of the same numbers.
assert_eq "ARCHITECTURE.md Layer: Primitives core/ = 111" \
    "$(grep -cE '\| \*\*Primitives\*\* \| .core/. \|.*\| 111 JS \|' "$WEB/machine_doc_v1/ARCHITECTURE.md")" "1"
assert_eq "ARCHITECTURE.md Layer: Webclient = 56" \
    "$(grep -cE '\| \*\*Webclient\*\* \| .webclient/. \|.*\| 56 JS \|' "$WEB/machine_doc_v1/ARCHITECTURE.md")" "1"
assert_eq "ARCHITECTURE.md Layer: Views = 151" \
    "$(grep -cE '\| \*\*Views\*\* \| .views/. \|.*\| 151 JS \|' "$WEB/machine_doc_v1/ARCHITECTURE.md")" "1"
assert_eq "ARCHITECTURE.md Layer: Model = 42" \
    "$(grep -cE '\| \*\*Model\*\* \| .model/. \|.*\| 42 JS \|' "$WEB/machine_doc_v1/ARCHITECTURE.md")" "1"
assert_eq "ARCHITECTURE.md Layer table covers legacy/" \
    "$(grep -cE '\| \*\*Legacy\*\* \| .legacy/. \|' "$WEB/machine_doc_v1/ARCHITECTURE.md")" "1"
assert_eq "ARCHITECTURE.md Layer table covers libs/" \
    "$(grep -cE '\| .libs/. \|' "$WEB/machine_doc_v1/ARCHITECTURE.md")" "1"

# 16. DIRECTORY_MAP.md header count — single source of truth for the dir total.
#     238 (round 5): 237 - polyfills/ (DELETED entirely) + core/lib/
#     + search/embedded_actions_bar/.
assert_eq "DIRECTORY_MAP.md header says 238 directories" \
    "$(grep -cE '\*\*238 directories\*\*' "$WEB/machine_doc_v1/DIRECTORY_MAP.md")" "1"
assert_eq "DIRECTORY_MAP.md no stale '237 directories'" \
    "$(grep -cE '\*\*237 directories\*\*' "$WEB/machine_doc_v1/DIRECTORY_MAP.md")" "0"
# Cite-fingerprint: confirm the underlying count.
assert_eq "static/src has 238 directories (excl. gitignored .claude cruft)" \
    "$(find "$WEB/static/src" -type d -not -path '*/.claude*' | wc -l)" "238"
assert_eq "polyfills/ directory deleted" \
    "$([ -d "$WEB/static/src/polyfills" ] && echo 1 || echo 0)" "0"
assert_eq "DIRECTORY_MAP.md dropped the polyfills row" \
    "$(grep -c 'polyfills' "$WEB/machine_doc_v1/DIRECTORY_MAP.md")" "0"
assert_eq "DIRECTORY_MAP.md has a core/lib row" \
    "$(grep -cE '^\| .core/lib/. \|' "$WEB/machine_doc_v1/DIRECTORY_MAP.md")" "1"
assert_eq "DIRECTORY_MAP.md has a search/embedded_actions_bar row" \
    "$(grep -cE '^\| .search/embedded_actions_bar/. \|' "$WEB/machine_doc_v1/DIRECTORY_MAP.md")" "1"

# 17. TEST_TAGS.md untagged-files claim — exactly three files lack a web_* topic
#     tag.  Corrected 2026-06-01: the prior "ten files / nine with no @tagged"
#     enumeration was false — test_assets/test_reports/test_session_info/
#     test_web_save/test_web_search_read all carry web_* tags.  Reality: only
#     test_esm_pipeline.py, test_res_config_settings.py (no @tagged) and
#     test_res_config_doc_links.py (framework tags only) lack one.
assert_eq "TEST_TAGS.md says 'three test files' lack web_*" \
    "$(grep -cE 'three test files currently carry no .web_\*. topic tag' "$WEB/machine_doc_v1/TEST_TAGS.md")" "1"
assert_eq "TEST_TAGS.md no stale 'ten test files' claim" \
    "$(grep -cE 'ten test files currently carry no' "$WEB/machine_doc_v1/TEST_TAGS.md")" "0"

# 18. ESM pipeline moved to the declarative registry (odoo/tools/assets/):
#     the assetsbundle frozensets (_ESM_APP_BUNDLES / ESM_BUNDLES /
#     DYNAMIC_ESM_BUNDLES / IMPORT_MAP_INCLUDES) are GONE — bundle membership
#     is declared per-module under the manifest 'esm' key and aggregated by
#     esm_registry().  Assert the symbols by existence, not line number
#     (assetsbundle.py is now the assetsbundle/ package; native-node helpers
#     moved to ir_qweb_assets.py).
PYBASE="/home/marin/Odoo/addons/odoo/odoo/addons/base/models"
PYTOOLS="/home/marin/Odoo/addons/odoo/odoo/tools/assets"
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
assert_eq "ESM_BUNDLING.md documents the manifest 'esm' key" \
    "$(grep -c 'dynamic_children' "$WEB/machine_doc_v1/ESM_BUNDLING.md")" "4"
assert_eq "ESM_BUNDLING.md no stale _ESM_APP_BUNDLES table row" \
    "$(grep -c '_ESM_APP_BUNDLES' "$WEB/machine_doc_v1/ESM_BUNDLING.md")" "1"

# 19. Symbols named in STATE_MANAGEMENT.md "Key files" block. Asserted by
#     existence, not line number — the cites used to drift 20-50 lines per
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
assert_eq "webclient.js emits CLEAR_CACHES on SW hard refresh" \
    "$(grep -c 'CLEAR_CACHES' "$WEB/static/src/webclient/webclient.js")" "1"
assert_eq "rpc.js is the CLEAR_CACHES listener" \
    "$(grep -c 'addEventListener(RpcEvent.CLEAR_CACHES' "$WEB/static/src/core/network/rpc.js")" "1"

# 21. TEST_TAGS.md test-method counts — converted from approximate ("~37") to
#     precise on 2026-05-19.  Lock both the doc text AND the codebase reality
#     so a future test addition fires immediately instead of leaving the doc
#     a year out of date with sterile "~" framing.
count_tag_methods() {
    # $1 = topic tag; emits the total test-method count across every class
    # whose @tagged decorator includes that tag (handles both `@tagged(...)`
    # and `@odoo.tests.tagged(...)` forms).
    local tag="$1"
    python3 - "$tag" "$WEB/tests" <<'PY'
import os, re, sys
tag, root = sys.argv[1], sys.argv[2]
total = 0
for fn in sorted(os.listdir(root)):
    if not fn.endswith(".py"):
        continue
    src = open(os.path.join(root, fn)).read()
    for blk in re.split(r"(?=^@(?:odoo\.tests\.)?tagged\([^)]*\)\s*\nclass\s+\w+)",
                        src, flags=re.MULTILINE):
        m = re.match(r"@(?:odoo\.tests\.)?tagged\(([^)]*)\)\s*\nclass\s+\w+", blk)
        if not m:
            continue
        tags = re.findall(r"['\"]([^'\"]+)['\"]", m.group(1))
        if tag in tags:
            total += len(re.findall(r"^    (?:async\s+)?def\s+test_\w+",
                                    blk, flags=re.MULTILINE))
print(total)
PY
}
for spec in \
    "web_unit:85" \
    "web_http:62" \
    "web_tour:5" \
    "web_js:36" \
    "web_perf:25" \
    "web_benchmark:8" \
    "click_all:2"; do
    tag="${spec%:*}"
    expected="${spec##*:}"
    actual=$(count_tag_methods "$tag")
    assert_eq "TEST_TAGS @tagged($tag) method count" "$actual" "$expected"
    # And the doc must cite the matching number.
    assert_eq "TEST_TAGS.md cites $expected for $tag" \
        "$(grep -cE "\`$tag\`.*\| $expected methods" "$WEB/machine_doc_v1/TEST_TAGS.md")" "1"
done

# 20. (removed) JS_FILE_INDEX body-header assertions — JS_FILE_INDEX.md deleted
#     2026-06-02.  Per-section counts are verified by the filesystem loop (§6).

# ------- Round 5 (2026-07-02): new mechanisms from this audit wave -------

# 22. CI typecheck gate is a BLOCKING drift-zero ratchet (floor committed in
#     tooling/ratchet/baselines/tsc.json), not the old warn-only annotate job.
TYPECHECK_YML="/home/marin/Odoo/addons/odoo/.github/workflows/typecheck.yml"
assert_eq "typecheck.yml has no continue-on-error key (blocking gate)" \
    "$(grep -c 'continue-on-error:' "$TYPECHECK_YML")" "0"
assert_eq "typecheck.yml enforces via tooling/ratchet" \
    "$(grep -c 'tooling/ratchet/ratchet.py tsc' "$TYPECHECK_YML")" "3"
assert_eq "JSDOC doc: warn-only claim replaced by blocking ratchet" \
    "$(grep -c 'continue-on-error: true' "$WEB/machine_doc_v1/JSDOC_TYPE_TIGHTENING.md")" "0"
assert_eq "JSDOC doc cites the 1917 floor" \
    "$(grep -c '1917' "$WEB/machine_doc_v1/JSDOC_TYPE_TIGHTENING.md")" "1"
tsc_floor=$(python3 -c "import json;print(json.load(open('/home/marin/Odoo/addons/odoo/tooling/ratchet/baselines/tsc.json'))['count'])" 2>/dev/null || echo "missing")
assert_eq "committed tsc ratchet floor is 1917" "$tsc_floor" "1917"

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
    "$(grep -c 'reactiveRenderers' "$WEB/static/src/model/model.js")" "4"
assert_eq "pivot + graph renderers/models use useReactiveModel (4 files)" \
    "$(grep -rln 'useReactiveModel' "$WEB/static/src/views" --include='*.js' | wc -l)" "4"
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
assert_eq "ROUTE_MAP notes the /web/tests/legacy removal" \
    "$(grep -c 'was \*\*removed\*\* along with the whole legacy QUnit chain' "$WEB/machine_doc_v1/ROUTE_MAP.md")" "1"
assert_eq "route handler count = 73 (reality check)" \
    "$(cat "$WEB"/controllers/*.py | grep -cE '@(http\.)?route\(')" "73"
assert_eq "ROUTE_MAP total row says 73 handlers" \
    "$(grep -c '73 handlers / ~105 URL variants' "$WEB/machine_doc_v1/ROUTE_MAP.md")" "1"

# 32. ADR index (core-root doc/adr) lists ADR-0011.
assert_eq "doc/adr/README.md indexes ADR-0011" \
    "$(grep -c '0011-persistence-backend-port' /home/marin/Odoo/addons/odoo/doc/adr/README.md)" "1"

echo ""
echo "================================================================"
echo "TOTAL: $PASS passed, $FAIL failed (round 6 — 2026-07-10 path + de-pin reconcile)"
echo "================================================================"
exit $FAIL
