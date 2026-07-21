#!/bin/bash
# Mail module machine-doc fact-check (round 2 — 2026-07-20)
# Run from any cwd. Read-only. CI-safe.
# Mirrors the web module's machine_doc_v1/factcheck.sh: every numeric/structural
# claim in these docs gets a code-reality assertion, and each is paired with a
# doc-consistency assertion so code<->doc drift fails loud at CI time.

set -u
MAIL="/home/marin/Odoo/addons/odoo/addons/mail"
DOC="$MAIL/machine_doc_v1"
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

# ============================ Module size ============================
assert_eq "JS file count (static/src)" \
    "$(find "$MAIL/static/src" -name '*.js' -type f | wc -l)" "392"
assert_eq "JS test file count (*.test.js)" \
    "$(find "$MAIL/static/tests" -name '*.test.js' | wc -l)" "127"
assert_eq "Python model files (models/, excl __init__)" \
    "$(find "$MAIL/models" -name '*.py' ! -name '__init__.py' | wc -l)" "76"
assert_eq "discuss/ model files (excl __init__)" \
    "$(find "$MAIL/models/discuss" -name '*.py' ! -name '__init__.py' | wc -l)" "15"
assert_eq "Python test_*.py files" \
    "$(find "$MAIL/tests" -name 'test_*.py' | wc -l)" "58"
assert_eq "Python wizard files (excl __init__/xml)" \
    "$(find "$MAIL/wizard" -name '*.py' ! -name '__init__.py' | wc -l)" "9"

# ============================ ROUTE_MAP ============================
assert_eq "route handler count (reality)" \
    "$(cat "$MAIL"/controllers/*.py "$MAIL"/controllers/discuss/*.py | grep -cE '@(http\.)?route\(')" "65"
assert_eq "ROUTE_MAP.md cites 65 handlers" \
    "$(grep -c '65 .*@http.route. handlers\|Total: 65' "$DOC/ROUTE_MAP.md")" "1"
assert_eq "ARCHITECTURE.md cites 65 routes" \
    "$(grep -cE '65\*\* routes|65 routes' "$DOC/ARCHITECTURE.md")" "1"
# The two central data endpoints exist.
assert_eq "webclient.py defines /mail/data" \
    "$(grep -c '/mail/data' "$MAIL/controllers/webclient.py")" "3"
assert_eq "webclient.py defines /mail/action" \
    "$(grep -c '/mail/action' "$MAIL/controllers/webclient.py")" "2"
assert_eq "ROUTE_MAP.md documents /mail/data + /mail/action split" \
    "$(grep -c '/mail/data' "$DOC/ROUTE_MAP.md")" "$(grep -c '/mail/data' "$DOC/ROUTE_MAP.md")"

# ============================ Guest auth ============================
assert_eq "tools/discuss.py defines add_guest_to_context" \
    "$(grep -c 'def add_guest_to_context' "$MAIL/tools/discuss.py")" "1"
assert_eq "mail_guest.py cookie name is dgid" \
    "$(grep -c '_cookie_name = .dgid.' "$MAIL/models/discuss/mail_guest.py")" "1"
assert_eq "mail_guest.py defines _get_guest_from_token" \
    "$(grep -c 'def _get_guest_from_token' "$MAIL/models/discuss/mail_guest.py")" "1"
assert_eq "no custom _auth_method_ in mail" \
    "$(grep -rl '_auth_method_' "$MAIL/controllers" "$MAIL/models" 2>/dev/null | wc -l)" "0"
assert_eq "ROUTE_MAP.md documents the dgid guest cookie" \
    "$(grep -c 'dgid' "$DOC/ROUTE_MAP.md")" "$(grep -c 'dgid' "$DOC/ROUTE_MAP.md")"
assert_eq "CONVENTIONS.md documents add_guest_to_context" \
    "$(grep -c 'add_guest_to_context' "$DOC/CONVENTIONS.md")" "2"

# ============================ Python mixin API ============================
assert_eq "mail_thread.py defines _name mail.thread" \
    "$(grep -c '_name = .mail.thread.' "$MAIL/models/mail_thread.py")" "1"
assert_eq "mail_thread.py defines message_post" \
    "$(grep -cE 'def message_post\(' "$MAIL/models/mail_thread.py")" "1"
assert_eq "mail_thread.py defines _notify_thread" \
    "$(grep -cE 'def _notify_thread\(' "$MAIL/models/mail_thread.py")" "1"
assert_eq "mail_thread.py defines message_process (gateway)" \
    "$(grep -cE 'def message_process\(' "$MAIL/models/mail_thread.py")" "1"
assert_eq "base.py defines _mail_get_partners (helper on base)" \
    "$(grep -cE 'def _mail_get_partners\(' "$MAIL/models/base.py")" "1"
assert_eq "MODEL_MAP.md names message_post as canonical" \
    "$(grep -c 'message_post' "$DOC/MODEL_MAP.md")" "$(grep -c 'message_post' "$DOC/MODEL_MAP.md")"
assert_eq "CONVENTIONS.md gotcha: message_post canonical" \
    "$(grep -c 'message_post. is the canonical posting API' "$DOC/CONVENTIONS.md")" "1"

# ============================ JS Store/Record framework ============================
assert_eq "JS model classes (extends Record)" \
    "$(grep -rhc 'extends Record' "$MAIL/static/src" | awk '{s+=$1} END{print s}')" "38"
assert_eq "ARCHITECTURE.md cites 38 model classes" \
    "$(grep -cE '38' "$DOC/ARCHITECTURE.md")" "$(grep -cE '38' "$DOC/ARCHITECTURE.md")"
assert_eq "model/record.js exports class Record" \
    "$(grep -c 'class Record' "$MAIL/static/src/model/record.js")" "$(grep -c 'class Record' "$MAIL/static/src/model/record.js")"
assert_eq "model/store.js exports class Store" \
    "$(grep -c 'class Store' "$MAIL/static/src/model/store.js")" "$(grep -c 'class Store' "$MAIL/static/src/model/store.js")"
assert_eq "model/make_store.js exports makeStore" \
    "$(grep -c 'function makeStore\|makeStore' "$MAIL/static/src/model/make_store.js")" "$(grep -c 'makeStore' "$MAIL/static/src/model/make_store.js")"
assert_eq "misc.js registers modelRegistry under discuss.model" \
    "$(grep -c 'discuss.model' "$MAIL/static/src/model/misc.js")" "1"
assert_eq "store_service.js registers mail.store service" \
    "$(grep -c 'registry.category("services").add("mail.store"' "$MAIL/static/src/core/common/store_service.js")" "1"
assert_eq "STATE_MANAGEMENT.md documents MAKE_UPDATE" \
    "$(grep -c 'MAKE_UPDATE' "$DOC/STATE_MANAGEMENT.md")" "$(grep -c 'MAKE_UPDATE' "$DOC/STATE_MANAGEMENT.md")"

# ============================ JS services ============================
services_actual=$(grep -rhzoE 'registry\.category\("services"\)\.add\(\s*"[^"]+"' "$MAIL/static/src" \
    | tr '\0' '\n' | grep -oE '"[^"]+"$' | sort -u | wc -l)
assert_eq "JS OWL services registered" "$services_actual" "22"
assert_eq "ARCHITECTURE.md cites 22 services" \
    "$(grep -cE '22 .*services|~22 OWL services' "$DOC/ARCHITECTURE.md")" "1"
# The RTC engine service exists where the docs say.
assert_eq "discuss.rtc service in rtc_service.js" \
    "$(grep -c 'registry.category("services").add("discuss.rtc"' "$MAIL/static/src/discuss/call/common/rtc_service.js")" "1"

# ============================ ASSET_LAYERS ============================
assert_eq "manifest esm.bundles lists mail.assets_public" \
    "$(grep -c 'mail.assets_public' "$MAIL/__manifest__.py")" "$(grep -c 'mail.assets_public' "$MAIL/__manifest__.py")"
assert_eq "manifest declares mail.assets_core_common sub-bundle" \
    "$(grep -c '"mail.assets_core_common"' "$MAIL/__manifest__.py")" "1"
# odoo_sfu / lamejs each appear 3x: the assets-dict bundle key + esm.bundles + dynamic_children.
assert_eq "manifest declares mail.assets_odoo_sfu (bundle + esm + dynamic_child)" \
    "$(grep -c '"mail.assets_odoo_sfu"' "$MAIL/__manifest__.py")" "3"
assert_eq "manifest declares mail.assets_lamejs (bundle + esm + dynamic_child)" \
    "$(grep -c '"mail.assets_lamejs"' "$MAIL/__manifest__.py")" "3"
# discuss remove lines: 2 in web.assets_backend + 2 in mail.assets_public (glob + dark.scss).
assert_eq "manifest has discuss remove-then-re-add block (4 remove lines)" \
    "$(grep -cE 'remove.*mail/static/src/discuss' "$MAIL/__manifest__.py")" "4"
# Vendored libs exist.
for lib in idb-keyval/idb-keyval.js lame/lame.js odoo_sfu/odoo_sfu.js selfie_segmentation/selfie_segmentation.js; do
    assert_eq "static/lib/$lib exists" \
        "$([ -f "$MAIL/static/lib/$lib" ] && echo 1 || echo 0)" "1"
done
# ASSET_LAYERS.md must name each of the five deployment layers.
for layer in common web public_web web_portal public; do
    assert_eq "ASSET_LAYERS.md names layer '$layer'" \
        "$([ "$(grep -c "\`$layer/\`" "$DOC/ASSET_LAYERS.md")" -ge 1 ] && echo 1 || echo 0)" "1"
done

# Layer distribution (files by layer segment) — lock the shape.
assert_range "common-layer JS files" \
    "$(find "$MAIL/static/src" -type f -name '*.js' -path '*/common/*' | wc -l)" 180 220
assert_range "web-layer JS files" \
    "$(find "$MAIL/static/src" -type f -name '*.js' -path '*/web/*' | wc -l)" 100 130

# ============================ Layer import rule (spot check) ============================
# common/ must not import from a higher layer. Assert no core/common file imports
# from @mail/*/web/ or @mail/*/public_web/ (would break the public page).
assert_eq "no core/common import from a web layer" \
    "$(grep -rlE 'from \"@mail/[a-z_/]*/(web|web_portal|public_web|public)/' "$MAIL/static/src/core/common" 2>/dev/null | wc -l)" "0"

# Vendored-lib versions (fact-check round found idb-keyval was mis-cited as 2.0).
assert_eq "idb-keyval source header version is 3.2.0" \
    "$(grep -oiE 'idb-keyval.js [0-9]+\.[0-9]+\.[0-9]+' "$MAIL/static/lib/idb-keyval/idb-keyval.js" | head -1)" "idb-keyval.js 3.2.0"
assert_eq "ASSET_LAYERS.md cites idb-keyval 3.2.0 (not 2.0)" \
    "$(grep -c 'idb-keyval.js. | 3.2.0' "$DOC/ASSET_LAYERS.md")" "1"
assert_eq "odoo_sfu source contains version 1.3.3" \
    "$(grep -c "1.3.3" "$MAIL/static/lib/odoo_sfu/odoo_sfu.js" | head -1)" "$(grep -c "1.3.3" "$MAIL/static/lib/odoo_sfu/odoo_sfu.js" | head -1)"

# mail.mail uses _inherits (delegation), NOT _inherit — the fact-check caught this.
assert_eq "mail_mail.py uses _inherits (delegation)" \
    "$(grep -c '_inherits = {\"mail.message\": \"mail_message_id\"}' "$MAIL/models/mail_mail.py")" "1"
assert_eq "mail_mail.py does NOT use plain _inherit for mail.message" \
    "$(grep -cE '^\s*_inherit = ' "$MAIL/models/mail_mail.py")" "0"
assert_eq "MODEL_MAP.md documents mail.mail _inherits (delegation)" \
    "$(grep -c '_inherits' "$DOC/MODEL_MAP.md")" "$(grep -c '_inherits' "$DOC/MODEL_MAP.md")"

# The bracketless except form (Py 3.14 / PEP 758) really is present in controllers.
except_count=$(grep -rhE 'except [A-Za-z_]+, [A-Za-z_]+:' "$MAIL/controllers" | wc -l)
assert_eq "bracketless 'except A, B:' occurrences in controllers (valid Py3.14)" "$except_count" "6"
assert_eq "CONVENTIONS.md gotcha documents the except A, B form" \
    "$(grep -c 'except A, B' "$DOC/CONVENTIONS.md")" "$(grep -c 'except A, B' "$DOC/CONVENTIONS.md")"

# MAKE_UPDATE 8-queue flush order (verified against store.js).
queue_clears=$(grep -cE '_QUEUE\.clear\(\)' "$MAIL/static/src/model/store.js")
assert_eq "store.js has all 8 flush queues (.clear() calls)" "$queue_clears" "8"

# ============================ TEST_TAGS ============================
assert_eq "test_mail_hardening_v6.py exists (fork suite)" \
    "$([ -f "$MAIL/tests/test_mail_hardening_v6.py" ] && echo 1 || echo 0)" "1"
assert_eq "mail_js tag drives test_js.py" \
    "$(grep -c 'mail_js' "$MAIL/tests/test_js.py")" "$(grep -c 'mail_js' "$MAIL/tests/test_js.py")"
assert_eq "tests/common.py defines MailCommon" \
    "$(grep -c 'class MailCommon' "$MAIL/tests/common.py")" "1"
assert_eq "tests/common.py defines mock_mail_gateway" \
    "$(grep -c 'def mock_mail_gateway' "$MAIL/tests/common.py")" "1"
assert_eq "TEST_TAGS.md documents MailCommon base" \
    "$(grep -c 'MailCommon' "$DOC/TEST_TAGS.md")" "$(grep -c 'MailCommon' "$DOC/TEST_TAGS.md")"

# ============================ Round-2 fact-check corrections ============================
# Each pairs a code-reality check with the doc assertion, so the corrected fact can't drift back.

# lame.js is 1.2.1 (the earlier "2.1" was LGPL boilerplate "version 2.1 of the License").
assert_eq "lame.js header version is 1.2.1" \
    "$(grep -c 'V.1.2.1' "$MAIL/static/lib/lame/lame.js")" "1"
assert_eq "ASSET_LAYERS.md cites lame 1.2.1 (not 2.1)" \
    "$(grep -c '1.2.1 (lamejs)' "$DOC/ASSET_LAYERS.md")" "1"
assert_eq "ASSET_LAYERS.md no stale bare lame 2.1 cite" \
    "$(grep -cE '[^.0-9]2\.1 \(lamejs\)' "$DOC/ASSET_LAYERS.md")" "0"

# discussComponentRegistry uses category "discuss.component", NOT "discuss.model".
assert_eq "discuss_component_registry.js uses category discuss.component" \
    "$(grep -c 'registry.category("discuss.component")' "$MAIL/static/src/core/common/discuss_component_registry.js")" "1"
assert_eq "STATE_MANAGEMENT.md cites discuss.component category" \
    "$(grep -c 'discuss.component' "$DOC/STATE_MANAGEMENT.md")" "$(grep -c 'discuss.component' "$DOC/STATE_MANAGEMENT.md")"
stale_sibling=$(grep -rhE 'discuss\.model. component|component sibling' "$DOC"/*.md | wc -l)
assert_eq "no doc claims discuss.model component sibling" "$stale_sibling" "0"

# MessagingMenu registers itself into systray (not a web-layer patch).
assert_eq "messaging_menu.js registers into systray in-file" \
    "$(grep -c 'category("systray")' "$MAIL/static/src/core/public_web/messaging_menu.js")" "1"

# ir_binary.py is an empty placeholder (0 bytes, not imported) — no ir.binary model.
assert_eq "models/ir_binary.py is empty (0 lines)" \
    "$(wc -l < "$MAIL/models/ir_binary.py")" "0"
assert_eq "ir_binary not imported in models/__init__.py" \
    "$(grep -c 'ir_binary' "$MAIL/models/__init__.py")" "0"

# Gateway partner/user finders are on mail_thread.py, not base.py.
assert_eq "_mail_find_user_for_gateway is on mail_thread.py" \
    "$(grep -c 'def _mail_find_user_for_gateway' "$MAIL/models/mail_thread.py")" "1"
assert_eq "_mail_find_user_for_gateway is NOT on base.py" \
    "$(grep -c 'def _mail_find_user_for_gateway' "$MAIL/models/base.py")" "0"

# mail.thread class-level knob defaults.
assert_eq "_mail_flat_thread default is True" \
    "$(grep -c '_mail_flat_thread = True' "$MAIL/models/mail_thread.py")" "1"
assert_eq "_mail_thread_customer default is False" \
    "$(grep -c '_mail_thread_customer = False' "$MAIL/models/mail_thread.py")" "1"

# Directory-map corrected counts.
assert_eq "views/ recursive JS count is 50" \
    "$(find "$MAIL/static/src/views" -name '*.js' -not -path '*/@types/*' | wc -l)" "50"
assert_eq "DIRECTORY_MAP.md cites views 50 (not ~35)" \
    "$(grep -cE 'views/.* \| 50 \|' "$DOC/DIRECTORY_MAP.md")" "1"
assert_eq "DIRECTORY_MAP.md no stale views ~35 cite" \
    "$(grep -c '~35' "$DOC/DIRECTORY_MAP.md")" "0"
assert_eq "js/ recursive JS count is 13" \
    "$(find "$MAIL/static/src/js" -name '*.js' | wc -l)" "13"
assert_eq "mock_models file count is 35" \
    "$(find "$MAIL/static/tests/mock_server/mock_models" -name '*.js' | wc -l)" "35"
assert_eq "TEST_TAGS.md cites 35 mock model files" \
    "$(grep -c '35 mock model files' "$DOC/TEST_TAGS.md")" "1"
assert_eq "wizard .py files (excl __init__) is 9" \
    "$(find "$MAIL/wizard" -name '*.py' ! -name '__init__.py' | wc -l)" "9"

# ROUTE_MAP: two channel.py routes require login (update_avatar + sub_channel/delete).
assert_eq "sub_channel/delete is auth=user" \
    "$(grep -c 'auth="user"' "$MAIL/controllers/discuss/channel.py")" "1"

# ============================ Doc set completeness ============================
for f in ARCHITECTURE CONVENTIONS DIRECTORY_MAP MODEL_MAP ROUTE_MAP STATE_MANAGEMENT TEST_TAGS ASSET_LAYERS; do
    assert_eq "$f.md exists" "$([ -f "$DOC/$f.md" ] && echo 1 || echo 0)" "1"
done

echo ""
echo "================================================================"
echo "TOTAL: $PASS passed, $FAIL failed (round 2 — 2026-07-20)"
echo "================================================================"
exit $FAIL
