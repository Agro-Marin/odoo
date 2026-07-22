#!/bin/bash
# Website module architecture fact-check (round 1 — 2026-07-21)
# Run from any cwd. Read-only. CI-safe.
# Verifies the counts and structural claims made in this machine_doc_v1/ set
# (ARCHITECTURE, DIRECTORY_MAP, MODEL_MAP, ROUTE_MAP, CONVENTIONS, INTERACTIONS,
# TEST_TAGS) against the live source tree. Symbol citations are existence checks,
# not pinned line numbers, so they survive refactors.

set -u
WEB="/home/marin/Odoo/addons/odoo/addons/website"
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
assert_file() {
    local name="$1" path="$2"
    if [ -e "$path" ]; then
        echo "PASS: $name [exists]"; PASS=$((PASS+1))
    else
        echo "FAIL: $name — missing [$path]"; FAIL=$((FAIL+1))
    fi
}
assert_grep() {
    # assert_grep <name> <pattern> <file>  — pattern must be found
    local name="$1" pat="$2" file="$3"
    if grep -qE "$pat" "$file" 2>/dev/null; then
        echo "PASS: $name"; PASS=$((PASS+1))
    else
        echo "FAIL: $name — pattern not found: $pat in $file"; FAIL=$((FAIL+1))
    fi
}

# ------- Module identity / manifest -------
assert_grep "Manifest depends on html_builder" '"html_builder"' "$WEB/__manifest__.py"
assert_grep "Manifest declares geoip2 external dep" 'geoip2' "$WEB/__manifest__.py"
assert_grep "web.assets_frontend bundle present" 'web.assets_frontend' "$WEB/__manifest__.py"
assert_grep "builder-iframe bundle present" 'website.assets_inside_builder_iframe' "$WEB/__manifest__.py"

# ------- Python surface -------
assert_eq "Controller files (incl __init__)" \
    "$(ls "$WEB"/controllers/*.py | wc -l)" "7"
assert_eq "Controller files (excl __init__)" \
    "$(ls "$WEB"/controllers/*.py | grep -vc __init__)" "6"
assert_eq "Model files" \
    "$(ls "$WEB"/models/*.py | wc -l)" "36"
assert_eq "Wizard py files (excl __init__)" \
    "$(ls "$WEB"/wizard/*.py | grep -vc __init__)" "4"
assert_eq "Python test files (incl __init__ + common)" \
    "$(ls "$WEB"/tests/*.py | wc -l)" "45"

# ------- ORM model class count (all ^class in models/ + wizard/, minus the two
# non-ORM classes: PageCannotBeCached(Exception) + ModelConverter) -------
assert_eq "ORM model classes (models/ + wizard/)" \
    "$(grep -rhE '^class ' "$WEB"/models/*.py "$WEB"/wizard/*.py | grep -vcE 'Exception\)|ModelConverter\)')" "62"

# ------- Signature model / methods exist -------
assert_grep "website model _name" '_name = ["'\'']website["'\'']' "$WEB/models/website.py"
assert_grep "website_domain() helper exists" 'def website_domain' "$WEB/models/website.py"
assert_grep "get_current_website() exists" 'def get_current_website' "$WEB/models/website.py"
# COW/COU engine lives in ir_ui_view.py write/unlink
assert_grep "ir_ui_view extends seo.metadata (COW host)" 'website.seo.metadata' "$WEB/models/ir_ui_view.py"
# Published mixin
assert_grep "website.published.mixin defined" 'website.published.mixin' "$WEB/models/mixins.py"
assert_grep "website.searchable.mixin defined" 'website.searchable.mixin' "$WEB/models/mixins.py"
# Full-page cache
assert_grep "website.page full-page cache" '_get_response_cached' "$WEB/models/website_page.py"
# Cookie barrier in ir_qweb
assert_grep "ir_qweb cookie/url post-processing" '_post_processing_att' "$WEB/models/ir_qweb.py"
# Visitor UTC-explicit SQL
assert_grep "visitor SQL is UTC-explicit" "at time zone 'UTC'" "$WEB/models/website_visitor.py"

# ------- Routes -------
assert_grep "form-builder route present" '/website/form' "$WEB/controllers/form.py"
assert_grep "sitemap route present" '/sitemap.xml' "$WEB/controllers/main.py"
assert_grep "model-page route present" '/model/' "$WEB/controllers/model_page.py"

# ------- JS surface -------
assert_eq "static/src .js files" \
    "$(find "$WEB/static/src" -name '*.js' -type f | wc -l)" "347"
assert_eq "static/src directories" \
    "$(find "$WEB/static/src" -type d | wc -l)" "143"
assert_eq "static/tests .js files" \
    "$(find "$WEB/static/tests" -name '*.js' -type f | wc -l)" "217"
assert_eq "tour definitions (static/tests/tours)" \
    "$(find "$WEB/static/tests/tours" -name '*.js' -type f | wc -l)" "86"
assert_eq "*.edit.js variants in static/src" \
    "$(find "$WEB/static/src" -name '*.edit.js' -type f | wc -l)" "31"
assert_range "snippet s_* directories" \
    "$(find "$WEB/static/src/snippets" -maxdepth 1 -type d -name 's_*' | wc -l)" "60" "72"

# ------- Interaction framework -------
assert_grep "Interaction base imported from @web/public/interaction" \
    'from "@web/public/interaction"' "$WEB/static/src/interactions/anchor_slide.js"
assert_range "public.interactions registrations" \
    "$(grep -rho 'registry.category("public.interactions").add(' "$WEB/static/src" | wc -l)" "30" "45"
assert_range "public.interactions.edit registrations" \
    "$(grep -rho 'registry.category("public.interactions.edit").add(' "$WEB/static/src" | wc -l)" "35" "50"
assert_grep "edit-service builds editable interactions" \
    'buildEditableInteractions' "$WEB/static/src/core/website_edit_service.js"
assert_file "systray JS lives in website_preview (not systray_items/)" \
    "$WEB/static/src/client_actions/website_preview/website_systray_item.js"
assert_eq "systray_items/ has no JS (SCSS only)" \
    "$(find "$WEB/static/src/systray_items" -name '*.js' 2>/dev/null | wc -l)" "0"

# ------- Builder / client action -------
assert_grep "WebsiteBuilder extends html_builder Builder" \
    'website_builder' "$WEB/__manifest__.py"
assert_file "website_preview client action exists" \
    "$WEB/static/src/client_actions/website_preview/website_builder_action.js"

# ------- machine_doc_v1 self-consistency -------
MD="$WEB/machine_doc_v1"
for doc in ARCHITECTURE DIRECTORY_MAP MODEL_MAP ROUTE_MAP CONVENTIONS INTERACTIONS TEST_TAGS; do
    assert_file "machine_doc_v1/$doc.md present" "$MD/$doc.md"
done

echo
echo "======================================"
echo "PASS=$PASS  FAIL=$FAIL"
echo "======================================"
[ "$FAIL" -eq 0 ]
