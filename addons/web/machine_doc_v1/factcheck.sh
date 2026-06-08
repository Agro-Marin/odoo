#!/bin/bash
# Web module architecture fact-check (round 3 — doc-consistency assertions added)
# Run from any cwd. Read-only. CI-safe.
# Today: 2026-05-09

set -u
WEB="/home/marin/Odoo/addons/core/addons/web"
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
# 630 = 621 baseline (round 3, 2026-05-09)
#       + 9 from the 2026-05-19 action-executors extraction:
#            8 new files in webclient/actions (action_constants.js,
#            action_executors/{act_url,act_window,client,close,server}.js,
#            action_state.js, action_button_executor.js, client_actions.js)
#            and 1 new file in core/ alongside the executor extraction.
assert_eq "JS file count" "$(find "$WEB/static/src" -name "*.js" -type f | wc -l)" "630"

# ------- Type coverage -------
# 628 = 630 total - 2 intentional exclusions (module_loader + service_worker)
assert_eq "@ts-check coverage" \
    "$(grep -rl "@ts-check" "$WEB/static/src" --include="*.js" 2>/dev/null | wc -l)" "628"
assert_eq "Untyped JS files (intentional: module_loader + service_worker)" \
    "$(find "$WEB/static/src" -name "*.js" -type f -exec grep -L "@ts-check" {} + 2>/dev/null | wc -l)" "2"

# ------- Test scope -------
# 332 = 331 baseline + 1 paired test for the executor extraction.
assert_eq "Hoot test files" "$(find "$WEB/static/tests" -name "*.test.js" 2>/dev/null | wc -l)" "332"
assert_eq "Legacy QUnit JS files" "$(find "$WEB/static/tests/legacy" -name "*.js" 2>/dev/null | wc -l)" "28"
assert_eq "Files with QUnit. references" \
    "$(grep -rl "QUnit\." "$WEB/static/tests" --include="*.js" 2>/dev/null | wc -l)" "14"

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
assert_eq "Reactive class declarations (production)" "$reactive_prod" "0"

reactive_web=$(grep -rEln "$REACTIVE_PATTERN" "$WEB/static/src" 2>/dev/null | wc -l)
assert_eq "Reactive class declarations in core/addons/web" "$reactive_web" "0"

signalstore=$(count_prod_decls "$SIGNALSTORE_PATTERN")
assert_eq "SignalStore class declarations (production code)" "$signalstore" "23"

# Verify web_studio's parallel Reactive class is gone — replaced by SignalStore + toRaw().
web_studio_reactive_class=$(grep -c "^export class Reactive {" \
    /home/marin/Odoo/addons/enterprise/web_studio/static/src/client_action/utils.js 2>/dev/null)
assert_eq "web_studio's parallel Reactive class (deleted)" "$web_studio_reactive_class" "0"

# Verify the .raw() callers were correctly migrated to toRaw(this).
web_studio_raw_calls=$(grep -rc "\.raw()" /home/marin/Odoo/addons/enterprise/web_studio/static/src 2>/dev/null \
    | awk -F: '{ s += $NF } END { print s+0 }')
assert_eq "web_studio .raw() callers (replaced by toRaw(this))" "$web_studio_raw_calls" "0"

# ------- RUM Phase 1 — landed 2026-05-02 -------
# web_vitals_service.js captures LCP/FCP/CLS/TTFB via PerformanceObserver and
# beacons to /web/observability/cwv on pagehide.  See research doc Recommendation #9.
# Phase 2 (queryable model + dashboard) is tracked separately.
rum_telemetry=$(grep -rln "PerformanceObserver\|web-vitals" "$WEB/static/src" 2>/dev/null | wc -l)
assert_eq "PerformanceObserver/web-vitals (RUM Phase 1)" "$rum_telemetry" "1"

# sendBeacon usages: 5 files since the FormSaveCoordinator extraction
# pulled the urgent-save flow up one layer.  Inventory:
#   1. record_save.js              — actual sendBeacon() call (data persistence)
#   2. web_vitals_service.js       — CWV telemetry on pagehide (RUM)
#   3. form_save_coordinator.js    — coordinator's requestUrgentSave() entry point
#   4. form_controller.js          — controller delegates to the coordinator
#   5. relational_model.js         — model-level _urgentSave plumbing
# All five are part of the same urgent-save call graph; only #1 actually
# invokes navigator.sendBeacon().  #2 is the unrelated RUM beacon.
sendbeacon_files=$(grep -rln "sendBeacon" "$WEB/static/src" 2>/dev/null | wc -l)
assert_eq "sendBeacon usages (record_save + web_vitals + coordinator chain)" "$sendbeacon_files" "5"

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

# ------- View Transitions wrap on action navigation (G3, verified 2026-05-08) -------
# action_container.js wraps controller swaps in document.startViewTransition so
# the browser handles the cross-fade.  Falls through to plain render when the
# API is unavailable or the user prefers reduced motion.  Lock the actual
# call (not comments/docstrings mentioning the API) and the reduced-motion
# guard so a future refactor cannot silently strip them.
assert_eq "ActionContainer invokes document.startViewTransition" \
    "$(grep -cE 'document\.startViewTransition\(' "$WEB/static/src/webclient/actions/action_container.js")" "1"
assert_eq "ActionContainer respects prefers-reduced-motion" \
    "$(grep -c 'prefers-reduced-motion' "$WEB/static/src/webclient/actions/action_container.js")" "1"

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

# 1. Urgent-save optimistic locking — STATE_MANAGEMENT.md must reflect the fix.
assert_eq "STATE_MANAGEMENT urgent-save: stale 'divergence' wording removed" \
    "$(grep -c 'Optimistic-locking divergence' "$WEB/machine_doc_v1/STATE_MANAGEMENT.md")" "0"
assert_eq "STATE_MANAGEMENT urgent-save: 'parity (resolved 2026-05-08)' marker present" \
    "$(grep -c 'Optimistic-locking parity (resolved 2026-05-08)' "$WEB/machine_doc_v1/STATE_MANAGEMENT.md")" "1"
# Cite-fingerprint: the doc cites record_save.js:79-83; verify that line range
# still actually contains the urgentKwargs.last_write_date assignment.
assert_eq "record_save.js urgent path sets last_write_date (parity with normal path)" \
    "$(grep -c 'urgentKwargs.last_write_date' "$WEB/static/src/model/relational_model/record_save.js")" "1"

# 2. FormSaveCoordinator — CONVENTIONS.md gotcha #12 must reflect the rewrite.
assert_eq "CONVENTIONS gotcha #12: stale '5 \`true\` call sites' wording removed" \
    "$(grep -c '5 \`true\` call sites' "$WEB/machine_doc_v1/CONVENTIONS.md")" "0"
assert_eq "CONVENTIONS gotcha #12: mentions FormSaveCoordinator" \
    "$(grep -c 'FormSaveCoordinator' "$WEB/machine_doc_v1/CONVENTIONS.md")" "1"
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

# 3. ARCHITECTURE.md JS file counts — sites previously cited 615 then 621;
#    should now be 630 after the 2026-05-19 action-executors extraction.
assert_eq "ARCHITECTURE.md no stale '615' JS file count" \
    "$(grep -cE '615 (JavaScript|JS)' "$WEB/machine_doc_v1/ARCHITECTURE.md")" "0"
assert_eq "ARCHITECTURE.md no stale '621' JS file count" \
    "$(grep -cE '621 (JavaScript|JS)' "$WEB/machine_doc_v1/ARCHITECTURE.md")" "0"
assert_eq "ARCHITECTURE.md JS count cited at two prose sites" \
    "$(grep -cE '630 (JavaScript|JS)' "$WEB/machine_doc_v1/ARCHITECTURE.md")" "2"
# (The third site is in a markdown table cell `| JavaScript (src) | 630 |` —
# pattern above won't match because of the pipe layout, so check it separately.)
assert_eq "ARCHITECTURE.md JS table cell" \
    "$(grep -cE '\| JavaScript \(src\) \| 630 \|' "$WEB/machine_doc_v1/ARCHITECTURE.md")" "1"

# 4. Pattern 4 inventory — STATE_MANAGEMENT.md should enumerate verified sites
#    rather than implying an open population.
assert_eq "STATE_MANAGEMENT lists Pattern 4 verified-inventory table" \
    "$(grep -c 'Verified inventory (2026-05-09, revised)' "$WEB/machine_doc_v1/STATE_MANAGEMENT.md")" "1"

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
    "$(grep -c "imported.name='Reactive'" /home/marin/Odoo/addons/core/eslint.config.mjs)" "0"

# 6. JS_FILE_INDEX.md per-section subtotals — lock the post-refactor numbers.
#    The doc keeps a Claimed/Actual/Δ table that's hand-maintained; if the
#    actual file count drifts from the doc's "Actual" column, this assertion
#    fires.  Bumping the assertion forces the contributor to also bump the
#    doc, keeping the two in lockstep.
assert_eq "JS_FILE_INDEX top-line: 630 files" \
    "$(grep -cE '\*\*630 files\*\*' "$WEB/machine_doc_v1/JS_FILE_INDEX.md")" "1"
assert_eq "JS_FILE_INDEX no stale '621 files' top-line" \
    "$(grep -cE '\*\*621 files\*\*' "$WEB/machine_doc_v1/JS_FILE_INDEX.md")" "0"
assert_eq "JS_FILE_INDEX no stale '615 files' top-line" \
    "$(grep -cE '\*\*615 files\*\*' "$WEB/machine_doc_v1/JS_FILE_INDEX.md")" "0"
# Per-section actual subtotals — three drifted (views, model, services) and
# the others held.  Lock all eight so future drift trips on commit.
for section_check in \
    "components/:74" \
    "core/:102" \
    "fields/:111" \
    "views/:144" \
    "webclient/:54" \
    "model/:34" \
    "services/:35" \
    "ui/:20"; do
    section="${section_check%:*}"
    expected="${section_check##*:}"
    actual=$(find "$WEB/static/src/$section" -name "*.js" -type f 2>/dev/null | wc -l)
    assert_eq "static/src/$section JS count matches JS_FILE_INDEX 'Actual'" \
        "$actual" "$expected"
done

# 7. Gotcha #10 cite-fingerprint: archiveEnabled getter shape.
#    The form_controller.js:586 getter must check both "active" and "x_active";
#    multi_record_controller.js delegates to computeArchiveEnabled().  These
#    are the cited code surfaces; if either changes shape the doc needs review.
assert_eq "form_controller has archiveEnabled getter" \
    "$(grep -c 'get archiveEnabled()' "$WEB/static/src/views/form/form_controller.js")" "1"
assert_eq "form_controller archiveEnabled checks 'active' field" \
    "$(grep -cE '"active" in activeFields' "$WEB/static/src/views/form/form_controller.js")" "1"
assert_eq "form_controller archiveEnabled has x_active fallback" \
    "$(grep -cE '"x_active" in activeFields' "$WEB/static/src/views/form/form_controller.js")" "1"
assert_eq "multi_record_controller delegates to computeArchiveEnabled" \
    "$(grep -c 'computeArchiveEnabled(this.props.fields)' "$WEB/static/src/views/multi_record_controller.js")" "1"
assert_eq "CONVENTIONS gotcha #10 cite line range corrected (586-595)" \
    "$(grep -c 'form_controller.js:586-595' "$WEB/machine_doc_v1/CONVENTIONS.md")" "1"
assert_eq "CONVENTIONS gotcha #10 stale line range (544-551) gone" \
    "$(grep -c 'form_controller.js:544-551' "$WEB/machine_doc_v1/CONVENTIONS.md")" "0"

# 8. Gotcha #5 cite-fingerprint: /web/image route count (claim: 17 patterns).
assert_eq "binary.py /web/image route mentions match doc claim (17)" \
    "$(grep -cE '/web/image' "$WEB/controllers/binary.py")" "17"

# 9. Gotcha #6 cite-fingerprint: graph view lazy-loads chartjs_lib bundle.
#     Doc claims this lazy-load defers Chart.js until first graph render.
#     If someone adds chartjs_lib to a parent bundle's static asset list,
#     this assertion is fine but the doc's framing becomes misleading; if
#     someone removes the loadBundle call (e.g. by inlining Chart.js
#     statically), this assertion fires.
assert_eq "graph_renderer.js lazy-loads web.chartjs_lib" \
    "$(grep -c 'loadBundle("web.chartjs_lib")' "$WEB/static/src/views/graph/graph_renderer.js")" "1"
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
        /home/marin/Odoo/addons/core \
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
assert_eq "rpc.js RPC_SETTINGS whitelist includes 'dedup'" \
    "$(grep -cE 'RPC_SETTINGS = new Set\(\[[^]]*"dedup"' "$WEB/static/src/core/network/rpc.js")" "1"
assert_eq "ARCHITECTURE.md documents orm.dedup proxy" \
    "$(grep -cE '\*\*`orm\.dedup`\*\*' "$WEB/machine_doc_v1/ARCHITECTURE.md")" "1"
assert_eq "ARCHITECTURE.md rpc.js whitelist mentions all 6 keys" \
    "$(grep -cE 'cache, silent, headers, timeout, retry, dedup' "$WEB/machine_doc_v1/ARCHITECTURE.md")" "1"

# 12. fullcalendar version — pre-2026-05-19 the vendored libs table said 6.1.20
#     while the bundles table said 7.0.0-rc.3 and the code shipped v7.  Lock
#     the table to 7.0.0-rc.3 (matches the code) and ban the stale 6.1.20 cite.
assert_eq "ARCHITECTURE.md fullcalendar row says 7.0.0-rc.3" \
    "$(grep -cE '\| .fullcalendar. \| 7\.0\.0-rc\.3 \|' "$WEB/machine_doc_v1/ARCHITECTURE.md")" "1"
assert_eq "ARCHITECTURE.md no stale fullcalendar 6.1.20" \
    "$(grep -cE 'fullcalendar.{0,30}6\.1\.20' "$WEB/machine_doc_v1/ARCHITECTURE.md")" "0"
assert_eq "fullcalendar vendored bundle is v7" \
    "$(grep -cE 'FullCalendar v7' "$WEB/static/lib/fullcalendar/fullcalendar.esm.js")" "1"

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

# 14. ARCHITECTURE.md table counts — 6 numeric claims locked.  Catches the
#     drift pattern that motivated this audit (counts grew, doc lagged).
assert_eq "ARCHITECTURE.md File Counts: Python tests = 39" \
    "$(grep -cE '\| Python \(tests\) \| 39 \|' "$WEB/machine_doc_v1/ARCHITECTURE.md")" "1"
assert_eq "ARCHITECTURE.md File Counts: JS tests = 416/332" \
    "$(grep -cE '\| JavaScript \(tests\) \| 416 \(incl\. 332' "$WEB/machine_doc_v1/ARCHITECTURE.md")" "1"
assert_eq "ARCHITECTURE.md File Counts: vendored libs = 94" \
    "$(grep -cE '\| JavaScript \(vendored libs\) \| 94 \|' "$WEB/machine_doc_v1/ARCHITECTURE.md")" "1"

# 15. ARCHITECTURE.md JavaScript Architecture table — lock the Layer subtotals.
#     These mirror the per-section JS_FILE_INDEX assertions but for the
#     ARCHITECTURE doc's view of the same numbers.
assert_eq "ARCHITECTURE.md Layer: Primitives core/ = 102" \
    "$(grep -cE '\| \*\*Primitives\*\* \| .core/. \|.*\| 102 JS \|' "$WEB/machine_doc_v1/ARCHITECTURE.md")" "1"
assert_eq "ARCHITECTURE.md Layer: Webclient = 54" \
    "$(grep -cE '\| \*\*Webclient\*\* \| .webclient/. \|.*\| 54 JS \|' "$WEB/machine_doc_v1/ARCHITECTURE.md")" "1"
assert_eq "ARCHITECTURE.md Layer: Views = 144" \
    "$(grep -cE '\| \*\*Views\*\* \| .views/. \|.*\| 144 JS \|' "$WEB/machine_doc_v1/ARCHITECTURE.md")" "1"
assert_eq "ARCHITECTURE.md Layer: Model = 34" \
    "$(grep -cE '\| \*\*Model\*\* \| .model/. \|.*\| 34 JS \|' "$WEB/machine_doc_v1/ARCHITECTURE.md")" "1"

# 16. DIRECTORY_MAP.md header count — single source of truth for the dir total.
assert_eq "DIRECTORY_MAP.md header says 237 directories" \
    "$(grep -cE '\*\*237 directories\*\*' "$WEB/machine_doc_v1/DIRECTORY_MAP.md")" "1"
assert_eq "DIRECTORY_MAP.md no stale '235 directories'" \
    "$(grep -cE '\*\*235 directories\*\*' "$WEB/machine_doc_v1/DIRECTORY_MAP.md")" "0"
# Cite-fingerprint: confirm the underlying count.
assert_eq "static/src has 237 directories" \
    "$(find "$WEB/static/src" -type d | wc -l)" "237"

# 17. TEST_TAGS.md "ten test files" claim — locks the new enumeration.
assert_eq "TEST_TAGS.md says 'ten test files' lack web_*" \
    "$(grep -cE 'ten test files currently carry no .web_\*. topic tag' "$WEB/machine_doc_v1/TEST_TAGS.md")" "1"
assert_eq "TEST_TAGS.md no stale 'three test files' claim" \
    "$(grep -cE 'three test files currently carry no' "$WEB/machine_doc_v1/TEST_TAGS.md")" "0"

# 18. Python line-number cites — assetsbundle.py and ir_qweb.py grew enough
#     between rounds to shift every cite by 14-70 lines.  Lock the canonical
#     symbols against their line numbers so the next bulk shift fails loud.
PYBASE="/home/marin/Odoo/addons/core/odoo/addons/base/models"
assert_eq "assetsbundle.py: _ESM_APP_BUNDLES at line 385" \
    "$(grep -cE '^    _ESM_APP_BUNDLES = ' "$PYBASE/assetsbundle.py")" "1"
assert_eq "assetsbundle.py: _ESM_APP_BUNDLES on cited line 385" \
    "$(sed -n '385p' "$PYBASE/assetsbundle.py" | grep -c '_ESM_APP_BUNDLES = ')" "1"
assert_eq "assetsbundle.py: ESM_BUNDLES on cited line 476" \
    "$(sed -n '476p' "$PYBASE/assetsbundle.py" | grep -c 'ESM_BUNDLES = ')" "1"
assert_eq "assetsbundle.py: DYNAMIC_ESM_BUNDLES on cited line 488" \
    "$(sed -n '488p' "$PYBASE/assetsbundle.py" | grep -c 'DYNAMIC_ESM_BUNDLES = ')" "1"
assert_eq "assetsbundle.py: IMPORT_MAP_INCLUDES on cited line 511" \
    "$(sed -n '511p' "$PYBASE/assetsbundle.py" | grep -c 'IMPORT_MAP_INCLUDES = ')" "1"
assert_eq "assetsbundle.py: esbuild_native_bundle on cited line 1018" \
    "$(sed -n '1018p' "$PYBASE/assetsbundle.py" | grep -c 'def esbuild_native_bundle')" "1"
assert_eq "ir_qweb.py: _get_native_module_nodes on cited line 4084" \
    "$(sed -n '4084p' "$PYBASE/ir_qweb.py" | grep -c 'def _get_native_module_nodes')" "1"

# 19. JS line-number cites for STATE_MANAGEMENT.md "Key files" block.
#     Pre-2026-05-19 every cite was stale by 20-50 lines; lock them.
assert_eq "form_controller.js:691 is save()" \
    "$(sed -n '691p' "$WEB/static/src/views/form/form_controller.js" | grep -cE 'async save\(')" "1"
assert_eq "form_controller.js:711 is discard()" \
    "$(sed -n '711p' "$WEB/static/src/views/form/form_controller.js" | grep -cE 'async discard\(')" "1"
assert_eq "form_controller.js:501 is beforeLeave()" \
    "$(sed -n '501p' "$WEB/static/src/views/form/form_controller.js" | grep -cE 'async beforeLeave\(')" "1"
assert_eq "record.js:393 is _applyChanges()" \
    "$(sed -n '393p' "$WEB/static/src/model/relational_model/record.js" | grep -cE '_applyChanges\(')" "1"
assert_eq "record.js:252 is discard()" \
    "$(sed -n '252p' "$WEB/static/src/model/relational_model/record.js" | grep -cE 'async discard\(')" "1"

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
    "web_unit:49" \
    "web_http:58" \
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

# 20. JS_FILE_INDEX body section headers — top-level table values must match
#     the per-section header LOC tags so a future bump in one updates both.
assert_eq "JS_FILE_INDEX body header: core/ says 102 files" \
    "$(grep -cE '^## core/ \(102 files' "$WEB/machine_doc_v1/JS_FILE_INDEX.md")" "1"
assert_eq "JS_FILE_INDEX body header: webclient/ says 54 files" \
    "$(grep -cE '^## webclient/ \(54 files' "$WEB/machine_doc_v1/JS_FILE_INDEX.md")" "1"
assert_eq "JS_FILE_INDEX body header: views/ says 144 files" \
    "$(grep -cE '^## views/ \(144 files' "$WEB/machine_doc_v1/JS_FILE_INDEX.md")" "1"
assert_eq "JS_FILE_INDEX body header: components/ says 74 files" \
    "$(grep -cE '^## components/ \(74 files' "$WEB/machine_doc_v1/JS_FILE_INDEX.md")" "1"

echo ""
echo "================================================================"
echo "TOTAL: $PASS passed, $FAIL failed (round 4 — 2026-05-19 audit fixes)"
echo "================================================================"
exit $FAIL
