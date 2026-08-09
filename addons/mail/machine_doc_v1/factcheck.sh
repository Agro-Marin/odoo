#!/bin/bash
# Mail module machine-doc fact-check (round 3 — 2026-07-26)
# Run from any cwd. Read-only. CI-safe.
# Mirrors the web module's machine_doc_v1/factcheck.sh: every numeric/structural
# claim in these docs gets a code-reality assertion, and each is paired with a
# doc-consistency assertion so code<->doc drift fails loud at CI time.
#
# INVARIANT (round 3): an assertion's `expected` must be a LITERAL. Round 2 shipped 14
# assertions of the form `assert_eq "..." "$(grep X f)" "$(grep X f)"` — a value compared
# to itself, which can never fail. They inflated the pass count while guarding nothing,
# and every error found in round 3 sat in the gaps they appeared to cover. If you cannot
# state the expected value as a literal, the claim is not yet fact-checked.

set -u
# Resolve every root from this script's own location, the way the rest of the
# repo's tooling does (tooling/_repo_root.py locates the checkout by its
# odoo-bin marker). These used to be absolute paths baked in from one
# developer's layout: on a checkout arranged differently every grep hit a
# missing file and returned empty, which the assertions reported as 156
# "failures" that were really one path error.
DOC="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
MAIL="$(dirname -- "$DOC")"
# A couple of claims depend on the FRAMEWORK, not on mail. Resolve it once, here,
# rather than spelling "$MAIL/../.." at each use — otherwise relocating the
# module makes those greps hit a missing file and return empty, which reads as a
# confusing failure. The marker check below turns that into one loud error.
ODOO="$(cd -- "$MAIL/../.." && pwd)"
if [ ! -f "$ODOO/odoo-bin" ]; then
    echo "FATAL: resolved framework root '$ODOO' has no odoo-bin." >&2
    echo "       This script expects <checkout>/addons/mail/machine_doc_v1/." >&2
    exit 2
fi
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
    "$(find "$MAIL/static/tests" -name '*.test.js' | wc -l)" "139"
assert_eq "Python model files (models/, excl __init__)" \
    "$(find "$MAIL/models" -name '*.py' ! -name '__init__.py' | wc -l)" "76"
assert_eq "discuss/ model files (excl __init__)" \
    "$(find "$MAIL/models/discuss" -name '*.py' ! -name '__init__.py' | wc -l)" "15"
assert_eq "Python test_*.py files" \
    "$(find "$MAIL/tests" -name 'test_*.py' | wc -l)" "64"
assert_eq "Python wizard files (excl __init__/xml)" \
    "$(find "$MAIL/wizard" -name '*.py' ! -name '__init__.py' | wc -l)" "9"

# ============================ ROUTE_MAP ============================
assert_eq "route handler count (reality)" \
    "$(cat "$MAIL"/controllers/*.py "$MAIL"/controllers/discuss/*.py | grep -cE '@(http\.)?route\(')" "65"
# The count above tallies DECORATORS, not URLs — decorators are multi-line, so a URL can be
# renamed or dropped without moving it (verified by mutation: deleting the
# /discuss/voice/worklet_processor URL line left the count at 65). Pin the URL set itself.
route_urls=$(python3 - "$MAIL" <<'PYEOF'
import ast,pathlib,hashlib,sys
urls=[]
for p in sorted(pathlib.Path(sys.argv[1],"controllers").rglob("*.py")):
    if p.name=="__init__.py": continue
    for cls in [n for n in ast.parse(p.read_text()).body if isinstance(n,ast.ClassDef)]:
        for fn in [n for n in cls.body if isinstance(n,ast.FunctionDef)]:
            for d in fn.decorator_list:
                if isinstance(d,ast.Call) and ast.unparse(d.func).endswith("route") and d.args:
                    v=ast.literal_eval(d.args[0])
                    urls += [v] if isinstance(v,str) else list(v)
u=sorted(set(urls))
print(f"{len(urls)} {len(u)} {hashlib.sha256(chr(10).join(u).encode()).hexdigest()}")
PYEOF
)
assert_eq "route URL strings (85 across 65 handlers, 20 of them font_to_img variants)" \
    "$(echo "$route_urls" | cut -d' ' -f1)" "85"
assert_eq "route URL set is exactly the documented one (sha256)" \
    "$(echo "$route_urls" | cut -d' ' -f3)" \
    "e556cf5066965974ee768f662a0c18d26efe859f8e8967c032a688d661f66363"
assert_eq "ROUTE_MAP.md cites 65 handlers" \
    "$(grep -c '65 .*@http.route. handlers\|Total: 65' "$DOC/ROUTE_MAP.md")" "1"
assert_eq "ARCHITECTURE.md cites 65 routes" \
    "$(grep -cE '65\*\* routes|65 routes' "$DOC/ARCHITECTURE.md")" "1"
# The two central data endpoints exist.
assert_eq "webclient.py defines /mail/data" \
    "$(grep -c '/mail/data' "$MAIL/controllers/webclient.py")" "3"
assert_eq "webclient.py defines /mail/action" \
    "$(grep -c '/mail/action' "$MAIL/controllers/webclient.py")" "2"
assert_eq "ROUTE_MAP.md marks /mail/data as the readonly endpoint" \
    "$(grep -c '| `/mail/data` | jsonrpc | \*\*yes\*\*' "$DOC/ROUTE_MAP.md")" "1"
assert_eq "webclient.py: /mail/data route is readonly=True" \
    "$(grep -c '"/mail/data", methods=\["POST"\], type="jsonrpc", auth="public", readonly=True' "$MAIL/controllers/webclient.py")" "1"
assert_eq "webclient.py: /mail/action route is NOT readonly" \
    "$(grep -c '@http.route("/mail/action", methods=\["POST"\], type="jsonrpc", auth="public")' "$MAIL/controllers/webclient.py")" "1"

# Framework contract the ROUTE_MAP legend depends on: `readonly` defaults to auth=="none",
# NOT to False. Confirmed against the live routing map (all 20 font_to_img URLs report
# readonly=True while declaring nothing). If upstream changes this, the legend goes stale.
assert_eq "framework routing.py is where we think it is" \
    "$([ -f "$ODOO/odoo/http/routing.py" ] && echo 1 || echo 0)" "1"
assert_eq "odoo/http: readonly defaults to (auth == 'none')" \
    "$(grep -c 'default_mode = fragment.get("readonly", default_auth == "none")' "$ODOO/odoo/http/routing.py")" "1"
assert_eq "ROUTE_MAP.md documents the auth=='none' readonly default" \
    "$(grep -c 'readonly` \*\*defaults to `auth == "none"`\*\*' "$DOC/ROUTE_MAP.md")" "1"
assert_eq "ROUTE_MAP.md no stale 'readonly=False' default claim" \
    "$(grep -c 'csrf=True` (http), `readonly=False`' "$DOC/ROUTE_MAP.md")" "0"
assert_eq "export_icon_to_png is mail's only auth='none' handler" \
    "$(grep -rc "auth=\"none\"" "$MAIL/controllers"/*.py "$MAIL/controllers/discuss"/*.py | grep -vc ':0')" "1"

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
    "$(grep -c 'dgid' "$DOC/ROUTE_MAP.md")" "2"
assert_eq "mail_guest.py cookie separator is |" \
    "$(grep -c '_cookie_separator = "|"' "$MAIL/models/discuss/mail_guest.py")" "1"
assert_eq "_get_guest_from_token rejects a non-digit id (no 500 on hostile cookie)" \
    "$(grep -c 'if not guest_id.isdigit():' "$MAIL/models/discuss/mail_guest.py")" "1"
assert_eq "_get_guest_from_context asserts a single-record guest" \
    "$(grep -c 'assert len(guest) <= 1' "$MAIL/models/discuss/mail_guest.py")" "1"
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
assert_eq "MODEL_MAP.md names message_post the central entry point" \
    "$(grep -c 'post a message on the record (central entry point)' "$DOC/MODEL_MAP.md")" "1"
assert_eq "CONVENTIONS.md gotcha: message_post canonical" \
    "$(grep -c 'message_post. is the canonical posting API' "$DOC/CONVENTIONS.md")" "1"

# ============================ JS Store/Record framework ============================
# Count models by .register() call sites — NOT by grepping 'extends Record'. That grep is
# wrong twice over (it misses `Attachment extends FileModelMixin(Record)` and falsely matches
# `StoreInternal extends RecordInternal`); the two errors cancel, so it returns the right
# number for the wrong reason and would drift silently.
assert_eq "JS model .register() call sites (38 models + base Record)" \
    "$(grep -rh '\.register();' "$MAIL/static/src" | wc -l)" "39"
assert_eq "base Record registers itself in model/record.js" \
    "$(grep -c '^Record.register();' "$MAIL/static/src/model/record.js")" "1"
assert_eq "Attachment is a model despite not matching 'extends Record'" \
    "$(grep -c 'export class Attachment extends FileModelMixin(Record)' "$MAIL/static/src/core/common/attachment_model.js")" "1"
assert_eq "StoreInternal is NOT a model (false 'extends Record' substring match)" \
    "$(grep -c 'export class StoreInternal extends RecordInternal' "$MAIL/static/src/model/store_internal.js")" "1"
assert_eq "ARCHITECTURE.md documents the .register()-based count" \
    "$(grep -c '38 (+ the base `Record` itself → 39 calls)' "$DOC/ARCHITECTURE.md")" "1"
assert_eq "core/common .register() call sites (30 models + Store singleton)" \
    "$(grep -rh '\.register();' "$MAIL/static/src/core/common" | wc -l)" "31"
# static _name split: 25 declare one, 14 are keyed by class name. Verified against the live
# modelRegistry in a browser (40 entries there: these 39 + ai.prompt.button from the `ai`
# module — the registry is global, so only the source-side count is assertable here).
named=0; unnamed=0
for f in $(grep -rl '\.register();' "$MAIL/static/src"); do
    if grep -q 'static _name = "' "$f"; then named=$((named+1)); else unnamed=$((unnamed+1)); fi
done
assert_eq "registered models declaring static _name" "$named" "25"
assert_eq "registered models keyed by class name (no static _name)" "$unnamed" "14"
assert_eq "CONVENTIONS.md gotcha 4 lists all 14, not just 5" \
    "$(grep -c '14 of the 39 registered models have no `static _name`' "$DOC/CONVENTIONS.md")" "1"
assert_eq "Thread really has no static _name (reached via pyToJsModels)" \
    "$(grep -c 'static _name' "$MAIL/static/src/core/common/thread_model.js")" "0"
assert_eq "Settings is fed by the res.users.settings bus type" \
    "$(grep -c '_bus_send("res.users.settings"' "$MAIL/models/res_users_settings.py")" "1"
assert_eq "model/record.js exports class Record" \
    "$(grep -c '^export class Record' "$MAIL/static/src/model/record.js")" "1"
assert_eq "model/store.js exports class Store extends Record" \
    "$(grep -c '^export class Store extends Record' "$MAIL/static/src/model/store.js")" "1"
assert_eq "model/make_store.js exports function makeStore" \
    "$(grep -c '^export function makeStore' "$MAIL/static/src/model/make_store.js")" "1"
assert_eq "misc.js registers modelRegistry under discuss.model" \
    "$(grep -c 'discuss.model' "$MAIL/static/src/model/misc.js")" "1"
assert_eq "store_service.js registers mail.store service" \
    "$(grep -c 'registry.category("services").add("mail.store"' "$MAIL/static/src/core/common/store_service.js")" "1"
assert_eq "STATE_MANAGEMENT.md documents the 8-queue flush order" \
    "$(grep -c 'FC  computes' "$DOC/STATE_MANAGEMENT.md")" "1"
assert_eq "store.js flush loop guards at 1000 iterations" \
    "$(grep -c 'if (++flushIterations > 1000)' "$MAIL/static/src/model/store.js")" "1"
assert_eq "STATE_MANAGEMENT.md cites the same 1000 cap" \
    "$(grep -c 'iteration cap 1000' "$DOC/STATE_MANAGEMENT.md")" "1"

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
assert_eq "manifest esm.bundles lists exactly the 4 documented ESM bundles" \
    "$(python3 -c "import ast,sys;m=ast.literal_eval(open('$MAIL/__manifest__.py').read());print(','.join(sorted(m['esm']['bundles'])))")" \
    "mail.assets_discuss_public_test_tours,mail.assets_lamejs,mail.assets_odoo_sfu,mail.assets_public"
# 16, not 17: web.assets_web_dark went away with the dark-mode rework (mail ships
# no *.dark.scss and web now answers both colour schemes from one stylesheet).
assert_eq "manifest declares 16 asset bundles" \
    "$(python3 -c "import ast;m=ast.literal_eval(open('$MAIL/__manifest__.py').read());print(len(m['assets']))")" "16"
assert_eq "manifest declares no dark bundle" \
    "$(grep -c 'assets_web_dark' "$MAIL/__manifest__.py")" "0"
assert_eq "mail ships no *.dark.scss" \
    "$(find "$MAIL/static/src" -name '*.dark.scss' | wc -l)" "0"
assert_eq "manifest declares mail.assets_core_common sub-bundle" \
    "$(grep -c '"mail.assets_core_common"' "$MAIL/__manifest__.py")" "1"
# odoo_sfu / lamejs each appear 3x: the assets-dict bundle key + esm.bundles + dynamic_children.
assert_eq "manifest declares mail.assets_odoo_sfu (bundle + esm + dynamic_child)" \
    "$(grep -c '"mail.assets_odoo_sfu"' "$MAIL/__manifest__.py")" "3"
assert_eq "manifest declares mail.assets_lamejs (bundle + esm + dynamic_child)" \
    "$(grep -c '"mail.assets_lamejs"' "$MAIL/__manifest__.py")" "3"
# discuss remove lines: 1 in web.assets_backend + 1 in mail.assets_public. Was 4 while
# each also stripped *.dark.scss; those two went with the dark-mode rework.
assert_eq "manifest has discuss remove-then-re-add block (2 remove lines)" \
    "$(grep -cE 'remove.*mail/static/src/discuss' "$MAIL/__manifest__.py")" "2"
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
# Pin the __info__ block, not a bare "1.3.3" — the bundle contains many dependency versions.
assert_eq "odoo_sfu __info__ declares version 1.3.3" \
    "$(grep -c "    version: '1.3.3'," "$MAIL/static/lib/odoo_sfu/odoo_sfu.js")" "1"
assert_eq "ASSET_LAYERS.md cites odoo_sfu 1.3.3" \
    "$(grep -c '| 1.3.3 |' "$DOC/ASSET_LAYERS.md")" "1"
assert_eq "selfie_segmentation build id is 0.1.1632777926" \
    "$(grep -oE '0\.1\.1632777926' "$MAIL/static/lib/selfie_segmentation/selfie_segmentation.js" | head -1)" "0.1.1632777926"

# mail.mail uses _inherits (delegation), NOT _inherit — the fact-check caught this.
assert_eq "mail_mail.py uses _inherits (delegation)" \
    "$(grep -c '_inherits = {\"mail.message\": \"mail_message_id\"}' "$MAIL/models/mail_mail.py")" "1"
assert_eq "mail_mail.py does NOT use plain _inherit for mail.message" \
    "$(grep -cE '^\s*_inherit = ' "$MAIL/models/mail_mail.py")" "0"
assert_eq "MODEL_MAP.md documents mail.mail delegation, not _inherit" \
    "$(grep -c 'Delegation inheritance, \*\*not\*\* `_inherit`' "$DOC/MODEL_MAP.md")" "1"
assert_eq "mail.alias.mixin is the other _inherits user (via alias_id)" \
    "$(grep -c '_inherits = {"mail.alias": "alias_id"}' "$MAIL/models/mail_alias_mixin.py")" "1"

# The bracketless except form (Py 3.14 / PEP 758) really is present in controllers.
except_count=$(grep -rhE 'except [A-Za-z_]+, [A-Za-z_]+:' "$MAIL/controllers" | wc -l)
assert_eq "bracketless 'except A, B:' occurrences in controllers (valid Py3.14)" "$except_count" "7"
assert_eq "CONVENTIONS.md gotcha documents the except A, B form" \
    "$(grep -c 'except A, B' "$DOC/CONVENTIONS.md")" "1"

# MAKE_UPDATE 8-queue flush order (verified against store.js).
queue_clears=$(grep -cE '_QUEUE\.clear\(\)' "$MAIL/static/src/model/store.js")
assert_eq "store.js has all 8 flush queues (.clear() calls)" "$queue_clears" "8"

# ============================ TEST_TAGS ============================
assert_eq "test_mail_hardening_v6.py exists (fork suite)" \
    "$([ -f "$MAIL/tests/test_mail_hardening_v6.py" ] && echo 1 || echo 0)" "1"
assert_eq "mail_js tags both HOOT suite classes in test_js.py" \
    "$(grep -c '@odoo.tests.tagged("post_install", "-at_install", "mail_js")' "$MAIL/tests/test_js.py")" "2"
assert_eq "tests/common.py defines MailCommon" \
    "$(grep -c 'class MailCommon' "$MAIL/tests/common.py")" "1"
assert_eq "tests/common.py defines mock_mail_gateway" \
    "$(grep -c 'def mock_mail_gateway' "$MAIL/tests/common.py")" "1"
assert_eq "TEST_TAGS.md documents the MailCommon tower" \
    "$(grep -c 'MailCommon' "$DOC/TEST_TAGS.md")" "3"
assert_eq "tests/common.py defines the MailCase middle tier" \
    "$(grep -c '^class MailCase' "$MAIL/tests/common.py")" "1"
assert_eq "tests/common.py defines the MockEmail foundation" \
    "$(grep -c '^class MockEmail' "$MAIL/tests/common.py")" "1"

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
    "$(grep -c 'discuss.component' "$DOC/STATE_MANAGEMENT.md")" "3"
assert_eq "modelRegistry really uses category discuss.model" \
    "$(grep -c 'registry.category("discuss.model")' "$MAIL/static/src/model/misc.js")" "1"
stale_sibling=$(grep -rhE 'discuss\.model. component|component sibling' "$DOC"/*.md | wc -l)
assert_eq "no doc claims discuss.model component sibling" "$stale_sibling" "0"

# MessagingMenu registers itself into systray (not a web-layer patch).
assert_eq "messaging_menu.js registers into systray in-file" \
    "$(grep -c 'category("systray")' "$MAIL/static/src/core/public_web/messaging_menu.js")" "1"

# ir_binary.py is an empty placeholder (0 bytes, not imported) — no ir.binary model.
# Measure BYTES, not lines: `wc -l` counts newlines, so a file holding `class Foo: pass`
# with no trailing newline reports 0 and would pass an "is empty" check while non-empty.
assert_eq "models/ir_binary.py is empty (0 bytes)" \
    "$(wc -c < "$MAIL/models/ir_binary.py")" "0"
assert_eq "models/discuss/ir_binary.py is empty (0 bytes)" \
    "$(wc -c < "$MAIL/models/discuss/ir_binary.py")" "0"
assert_eq "ir_binary not imported in models/__init__.py" \
    "$(grep -c 'ir_binary' "$MAIL/models/__init__.py")" "0"
assert_eq "ir_binary not imported in models/discuss/__init__.py" \
    "$(grep -c 'ir_binary' "$MAIL/models/discuss/__init__.py")" "0"

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

# ================= Round-3 fact-check: previously uncovered claims =================
# Everything below was wrong or missing in the docs and had NO assertion guarding it.

# XML totals. ARCHITECTURE.md claimed "~380"; the real module-wide total is 232 and its own
# breakdown only ever summed to 224 (it omitted wizard/security/test XML).
assert_eq "module-wide XML file count" "$(find "$MAIL" -name '*.xml' | wc -l)" "232"
assert_eq "static OWL template XML" "$(find "$MAIL/static/src" -name '*.xml' | wc -l)" "164"
assert_eq "views/ XML"   "$(find "$MAIL/views"  -name '*.xml' | wc -l)" "41"
assert_eq "data/ XML"    "$(find "$MAIL/data"   -name '*.xml' | wc -l)" "15"
assert_eq "wizard/ XML"  "$(find "$MAIL/wizard" -name '*.xml' | wc -l)" "6"
assert_eq "demo/ XML"    "$(find "$MAIL/demo"   -name '*.xml' | wc -l)" "4"
assert_eq "ARCHITECTURE.md cites the 232 XML total with its breakdown" \
    "$(grep -c '232 = 164 static OWL + 41 views + 15 data + 6 wizard + 4 demo + 1 security + 1 test' "$DOC/ARCHITECTURE.md")" "1"
assert_eq "ARCHITECTURE.md no stale ~380 XML cite" \
    "$(grep -c '~380' "$DOC/ARCHITECTURE.md")" "0"

# static/src/worklets/ — omitted entirely from DIRECTORY_MAP's top-level split, which left
# its rows summing to 391 against a real 392.
assert_eq "static/src/worklets/ holds the RTC audio worklet" \
    "$(find "$MAIL/static/src/worklets" -name '*.js' | wc -l)" "1"
assert_eq "DIRECTORY_MAP.md lists the worklets/ row" \
    "$(grep -c '| `worklets/` | 1 |' "$DOC/DIRECTORY_MAP.md")" "1"
# The top-level split must account for every static/src JS file.
top_split=$(( $(find "$MAIL/static/src/model" -name '*.js' | wc -l) \
            + $(find "$MAIL/static/src/core" -name '*.js' | wc -l) \
            + $(find "$MAIL/static/src/discuss" -name '*.js' | wc -l) \
            + $(find "$MAIL/static/src/chatter" -name '*.js' | wc -l) \
            + $(find "$MAIL/static/src/views" -name '*.js' | wc -l) \
            + $(find "$MAIL/static/src/utils" -name '*.js' | wc -l) \
            + $(find "$MAIL/static/src/js" -name '*.js' | wc -l) \
            + $(find "$MAIL/static/src/webclient" -name '*.js' | wc -l) \
            + $(find "$MAIL/static/src/worklets" -name '*.js' | wc -l) \
            + $(find "$MAIL/static/src" -maxdepth 1 -name '*.js' | wc -l) ))
assert_eq "DIRECTORY_MAP top-level split accounts for all static/src JS" \
    "$top_split" "$(find "$MAIL/static/src" -name '*.js' | wc -l)"

# Mock-server route count. TEST_TAGS.md claimed "~52"; the real figure is 39.
assert_eq "mail_mock_server.js registers 39 routes" \
    "$(grep -cE '^registerRoute\(' "$MAIL/static/tests/mock_server/mail_mock_server.js")" "39"
assert_eq "TEST_TAGS.md cites 39 mocked RPC routes (not ~52)" \
    "$(grep -c '39 mocked RPC routes' "$DOC/TEST_TAGS.md")" "1"
assert_eq "TEST_TAGS.md no stale ~52 cite" \
    "$(grep -c '~52' "$DOC/TEST_TAGS.md")" "0"

# JS test directory table. core/ was cited as 15 (really 16) and widgets/ as 2 (really 1);
# the two errors cancelled, so the table summed correctly while both rows were wrong.
assert_eq "static/tests/core/ test files"    "$(find "$MAIL/static/tests/core"    -name '*.test.js' | wc -l)" "22"
assert_eq "static/tests/widgets/ test files" "$(find "$MAIL/static/tests/widgets" -name '*.test.js' | wc -l)" "1"
assert_eq "static/tests/discuss/ test files" "$(find "$MAIL/static/tests/discuss" -name '*.test.js' | wc -l)" "43"
assert_eq "TEST_TAGS.md cites core/ 22" \
    "$(grep -c '| `core/` | 22 |' "$DOC/TEST_TAGS.md")" "1"
assert_eq "TEST_TAGS.md moved widgets/ to the '1 each' row" \
    "$(grep -c 'translation/`, `widgets/`' "$DOC/TEST_TAGS.md")" "1"

# Test-class tagging. Both @tagged and @odoo.tests.tagged spellings are in use; counting only
# the bare form undercounts (that is how "97 post_install classes" was reached).
tagged_total=$(grep -rhcE '^@(odoo\.tests\.)?tagged\(' "$MAIL/tests" | awk '{s+=$1} END{print s}')
tagged_post=$(grep -rhE '^@(odoo\.tests\.)?tagged\(' "$MAIL/tests" | grep -c 'post_install')
assert_eq "tagged test classes (both decorator spellings)" "$tagged_total" "135"
assert_eq "tagged classes carrying post_install" "$tagged_post" "120"
assert_eq "TEST_TAGS.md cites 120 of 135" \
    "$(grep -c 'Of \*\*135\*\* tagged classes, \*\*120\*\*' "$DOC/TEST_TAGS.md")" "1"
assert_eq "TEST_TAGS.md warns about the two decorator spellings" \
    "$(grep -c 'decorator spellings are in use' "$DOC/TEST_TAGS.md")" "1"

# Per-tag class counts that the docs assert in prose.
assert_eq "mail_hardening_v11 classes" \
    "$(grep -rhE '^@(odoo\.tests\.)?tagged\(' "$MAIL/tests/test_mail_hardening_v11.py" | grep -c 'mail_hardening_v11')" "7"
assert_eq "TEST_TAGS.md cites mail_hardening_v11 (7)" \
    "$(grep -c 'mail_hardening_v11` (7)' "$DOC/TEST_TAGS.md")" "1"
assert_eq "mail_controller classes (7 across 6 discuss files + mock_server_contract)" \
    "$(grep -rhE '^@(odoo\.tests\.)?tagged\(' "$MAIL/tests" | grep -c 'mail_controller')" "7"

# Controller file count: 19, not 21 — the docs were counting the two __init__.py, which is
# inconsistent with the models row (76, which excludes it).
assert_eq "controller files (excl __init__)" \
    "$(find "$MAIL/controllers" -name '*.py' ! -name '__init__.py' | wc -l)" "19"
assert_eq "ROUTE_MAP.md cites 19 controller files" \
    "$(grep -c '\*\*19\*\* controller files' "$DOC/ROUTE_MAP.md")" "1"
assert_eq "no doc still claims 21 controller files" \
    "$(grep -rc '21 controller files' "$DOC"/*.md | grep -vc ':0')" "0"
assert_eq "ARCHITECTURE.md cites 19 controller files" \
    "$(grep -c '| 19 files · \*\*65\*\* routes |' "$DOC/ARCHITECTURE.md")" "1"
assert_eq "ARCHITECTURE.md wizard row agrees with DIRECTORY_MAP (9, excl __init__)" \
    "$(grep -c '| Python wizards | 9 |' "$DOC/ARCHITECTURE.md")" "1"

# The layer import rule holds module-wide, not just in core/common.
assert_eq "no common/ file anywhere imports from a higher layer" \
    "$(grep -rlE 'from "@mail/[a-z_/]*/(web|web_portal|public_web|public)/' --include='*.js' "$MAIL/static/src" 2>/dev/null | grep -c '/common/')" "0"

# service_worker.js is in no bundle at all (CONVENTIONS gotcha 2 named a non-existent
# "@odoo-module ignore" annotation; the real evidence is manifest absence).
assert_eq "service_worker.js appears in no asset bundle" \
    "$(python3 -c "import ast;m=ast.literal_eval(open('$MAIL/__manifest__.py').read());print(sum(1 for b in m['assets'].values() for i in b if isinstance(i,str) and i.endswith('src/service_worker.js')))")" "0"
assert_eq "service_worker_utils.js IS exposed to HOOT" \
    "$(python3 -c "import ast;m=ast.literal_eval(open('$MAIL/__manifest__.py').read());print(int('mail/static/src/service_worker_utils.js' in m['assets']['web.assets_unit_tests']))")" "1"

# ============================ Doc set completeness ============================
for f in ARCHITECTURE CONVENTIONS DIRECTORY_MAP MODEL_MAP ROUTE_MAP STATE_MANAGEMENT TEST_TAGS ASSET_LAYERS; do
    assert_eq "$f.md exists" "$([ -f "$DOC/$f.md" ] && echo 1 || echo 0)" "1"
done

echo ""
echo "================================================================"
echo "TOTAL: $PASS passed, $FAIL failed (round 3 — 2026-07-26)"
echo "================================================================"
exit $FAIL
