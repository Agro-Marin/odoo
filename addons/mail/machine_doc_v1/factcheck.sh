#!/bin/bash
# Mail module machine-doc fact-check (round 4 — 2026-08-17)
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
#
# INVARIANT (round 4): MEASURE AGAINST HEAD, IN A CLEAN CHECKOUT. Several sessions work this
# workspace at once, so the working tree carries other people's uncommitted files. Measured in
# the shared checkout, this script reported 20 controller files and 54 test files against a
# HEAD that has 19 and 52 — the difference being one untracked controller and two untracked
# tests belonging to a session mid-flight. A count harvested from a dirty tree is somebody
# else's work committed into our docs as fact:
#
#     git -C <odoo> worktree add --detach <scratch>/odoo HEAD
#     bash <scratch>/odoo/addons/mail/machine_doc_v1/factcheck.sh
#     git -C <odoo> worktree remove <scratch>/odoo
#
# INVARIANT (round 4): A RENAME NEEDS TWO ASSERTIONS, NOT ONE. Pinning only the new name
# passes while every doc still teaches the old one, and an override written against a
# vanished hook compiles, overrides nothing and raises nothing. So each rename below asserts
# the new name exists, the old name is gone from the code, AND no doc still names it. Round 3
# was itself the counter-example: it went stale on the mixin rename and four of its
# assertions failed on a missing FILE, which reads as "the docs are wrong" and is not.

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
    "$(find "$MAIL/static/src" -name '*.js' -type f | wc -l)" "397"
assert_eq "JS test file count (*.test.js)" \
    "$(find "$MAIL/static/tests" -name '*.test.js' | wc -l)" "143"
assert_eq "Python model files (models/, excl __init__)" \
    "$(find "$MAIL/models" -name '*.py' ! -name '__init__.py' | wc -l)" "77"
assert_eq "discuss/ model files (excl __init__)" \
    "$(find "$MAIL/models/discuss" -name '*.py' ! -name '__init__.py' | wc -l)" "14"
assert_eq "Python test_*.py files" \
    "$(find "$MAIL/tests" -name 'test_*.py' | wc -l)" "55"
assert_eq "Python wizard files (excl __init__/xml)" \
    "$(find "$MAIL/wizard" -name '*.py' ! -name '__init__.py' | wc -l)" "9"

# ============================ ROUTE_MAP ============================
assert_eq "route handler count (reality)" \
    "$(cat "$MAIL"/controllers/*.py "$MAIL"/controllers/discuss/*.py | grep -cE '@(http\.)?route\(')" "64"
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
assert_eq "route URL strings (84 across 64 handlers, 20 of them font_to_img variants)" \
    "$(echo "$route_urls" | cut -d' ' -f1)" "84"
assert_eq "route URL set is exactly the documented one (sha256)" \
    "$(echo "$route_urls" | cut -d' ' -f3)" \
    "6e12c092cec25fc865dfa2a892d7f4789901f41eb648a29626b43c8555c86a8f"
assert_eq "ROUTE_MAP.md cites 64 handlers" \
    "$(grep -c 'Total: 64 .@http.route. handlers' "$DOC/ROUTE_MAP.md")" "1"
assert_eq "ARCHITECTURE.md cites 64 routes" \
    "$(grep -cE '\*\*64\*\* routes' "$DOC/ARCHITECTURE.md")" "1"
# The two central data endpoints exist.
assert_eq "webclient.py defines /mail/data" \
    "$(grep -c '/mail/data' "$MAIL/controllers/webclient.py")" "1"
assert_eq "webclient.py defines /mail/action" \
    "$(grep -c '/mail/action' "$MAIL/controllers/webclient.py")" "1"
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
# The mixins are models/mixin_<what they add>.py since coding_guidelines 2.2.1; `mail.thread`
# is `mixin.mail.thread` and models/mail_thread.py does not exist. Round 3 greps still named the
# old paths, so four assertions failed on a missing file rather than on anything being wrong.
assert_eq "mixin_mail_thread.py defines _name mixin.mail.thread" \
    "$(grep -c '_name = .mixin.mail.thread.' "$MAIL/models/mixin_mail_thread.py")" "1"
assert_eq "no models/mail_thread.py (pre-rename path)" \
    "$([ -e "$MAIL/models/mail_thread.py" ] && echo 1 || echo 0)" "0"
assert_eq "models/ holds 12 mixin_*.py files" \
    "$(find "$MAIL/models" -maxdepth 1 -name 'mixin_*.py' | wc -l)" "12"
assert_eq "discuss/ holds mixin_bus_listener.py" \
    "$([ -f "$MAIL/models/discuss/mixin_bus_listener.py" ] && echo 1 || echo 0)" "1"
assert_eq "no doc names a pre-rename mixin file path" \
    "$(grep -cE '`(mail_thread|mail_thread_cc|mail_thread_blacklist|mail_render_mixin|mail_activity_mixin|mail_alias_mixin|template_reset_mixin|bus_listener_mixin)\.py`' "$DOC"/*.md | grep -vc ':0')" "0"
assert_eq "mixin_mail_thread.py defines message_post" \
    "$(grep -cE 'def message_post\(' "$MAIL/models/mixin_mail_thread.py")" "1"
assert_eq "mixin_mail_thread.py defines _notify_thread" \
    "$(grep -cE 'def _notify_thread\(' "$MAIL/models/mixin_mail_thread.py")" "1"
assert_eq "mixin_mail_thread.py defines message_process (gateway)" \
    "$(grep -cE 'def message_process\(' "$MAIL/models/mixin_mail_thread.py")" "1"
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
assert_eq "JS model .register() call sites (39 models + base Record)" \
    "$(grep -rh '\.register();' "$MAIL/static/src" | wc -l)" "40"
assert_eq "base Record registers itself in model/record.js" \
    "$(grep -c '^Record.register();' "$MAIL/static/src/model/record.js")" "1"
assert_eq "Attachment is a model despite not matching 'extends Record'" \
    "$(grep -c 'export class Attachment extends FileModelMixin(Record)' "$MAIL/static/src/core/common/attachment_model.js")" "1"
assert_eq "StoreInternal is NOT a model (false 'extends Record' substring match)" \
    "$(grep -c 'export class StoreInternal extends RecordInternal' "$MAIL/static/src/model/store_internal.js")" "1"
assert_eq "ARCHITECTURE.md documents the .register()-based count" \
    "$(grep -c '39 (+ the base `Record` itself → 40 calls)' "$DOC/ARCHITECTURE.md")" "1"
# The inverse rule of CONVENTIONS.md §7.2. Both halves are pinned because the doc used to
# state the opposite ("always set inverse", "so RecordUses stays consistent") and neither was
# true: the store VALIDATES the pair and throws when the named field is absent, so following
# that advice on a relation with no reciprocal took the client down at boot.
assert_eq "JS relation declarations (fields.One + fields.Many)" \
    "$(grep -rhoE 'fields\.(One|Many)\(' "$MAIL/static/src" | wc -l)" "176"
assert_eq "JS relations declaring an inverse" \
    "$(grep -rhoE '\binverse:' "$MAIL/static/src" | wc -l)" "49"
assert_eq "CONVENTIONS.md cites 49 of 176 relations declaring an inverse" \
    "$(grep -c '49 of the 176 relations declare one' "$DOC/CONVENTIONS.md")" "1"
assert_eq "CONVENTIONS.md no longer tells you to always set inverse" \
    "$(grep -c 'always set .inverse' "$DOC/CONVENTIONS.md")" "0"
assert_eq "make_store validates the declared inverse against the target" \
    "$(grep -c 'has no fields.One()/fields.Many() named' "$MAIL/static/src/model/make_store.js")" "1"
assert_eq "RecordUses is maintained from the RecordList, not from inverse" \
    "$(grep -c '_\.uses\.add(recordList)' "$MAIL/static/src/model/record_list.js")" "7"

assert_eq "core/common .register() call sites (31 models + Store singleton)" \
    "$(grep -rh '\.register();' "$MAIL/static/src/core/common" | wc -l)" "32"
assert_eq "DIRECTORY_MAP.md cites core/common 32 register calls" \
    "$(grep -c '32 `.register()` calls' "$DOC/DIRECTORY_MAP.md")" "1"
# static _name split: 25 declare one, 14 are keyed by class name. Verified against the live
# modelRegistry in a browser (40 entries there: these 39 + ai.prompt.button from the `ai`
# module — the registry is global, so only the source-side count is assertable here).
named=0; unnamed=0
for f in $(grep -rl '\.register();' "$MAIL/static/src"); do
    if grep -q 'static _name = "' "$f"; then named=$((named+1)); else unnamed=$((unnamed+1)); fi
done
assert_eq "registered models declaring static _name" "$named" "25"
assert_eq "registered models keyed by class name (no static _name)" "$unnamed" "15"
assert_eq "CONVENTIONS.md gotcha 4 lists all 15, not just 5" \
    "$(grep -c '15 of the 40 registered models have no `static _name`' "$DOC/CONVENTIONS.md")" "1"
# MessagingMenu is the 15th: a core/common model with no static _name, added after round 3.
# Both docs enumerate the unnamed set, so both must name it or the list is a lie by omission.
assert_eq "CONVENTIONS.md gotcha 4 names MessagingMenu" \
    "$(grep -c '`MessagingMenu`' "$DOC/CONVENTIONS.md")" "1"
assert_eq "STATE_MANAGEMENT.md names MessagingMenu among the unnamed" \
    "$(grep -c '`MessagingMenu`' "$DOC/STATE_MANAGEMENT.md")" "1"
assert_eq "MessagingMenu really has no static _name" \
    "$(grep -c 'static _name' "$MAIL/static/src/core/common/messaging_menu_model.js")" "0"
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
assert_eq "JS OWL services registered" "$services_actual" "23"
assert_eq "ARCHITECTURE.md cites 23 services" \
    "$(grep -c '23 OWL services' "$DOC/ARCHITECTURE.md")" "1"
# mail.link_navigation is the 23rd. A count alone would pass with the table a row short,
# so pin the row too -- that is exactly how round 3 shipped a 22-row table calling itself 22.
assert_eq "mail.link_navigation service exists" \
    "$(grep -c 'registry.category("services").add("mail.link_navigation"' "$MAIL/static/src/core/common/link_navigation_service.js")" "1"
assert_eq "ARCHITECTURE.md service table has a mail.link_navigation row" \
    "$(grep -c '| `mail.link_navigation` |' "$DOC/ARCHITECTURE.md")" "1"
# Every registered service name must appear in the ARCHITECTURE.md table.
missing_svc=0
for svc in $(grep -rhzoE 'registry\.category\("services"\)\.add\(\s*"[^"]+"' "$MAIL/static/src" \
        | tr '\0' '\n' | grep -oE '"[^"]+"$' | tr -d '"' | sort -u); do
    grep -q "\`$svc\`" "$DOC/ARCHITECTURE.md" || { echo "  (missing from table: $svc)"; missing_svc=$((missing_svc+1)); }
done
assert_eq "every registered service appears in ARCHITECTURE.md's table" "$missing_svc" "0"
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
    "$(find "$MAIL/static/src" -type f -name '*.js' -path '*/web/*' | wc -l)" 110 145

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
assert_eq "mixin.mail.alias is the other _inherits user (via alias_id)" \
    "$(grep -c '_inherits = {"mail.alias": "alias_id"}' "$MAIL/models/mixin_mail_alias.py")" "1"

# The bracketless except form (Py 3.14 / PEP 758) really is present in controllers.
except_count=$(grep -rhE 'except [A-Za-z_]+, [A-Za-z_]+:' "$MAIL/controllers" | wc -l)
assert_eq "bracketless 'except A, B:' occurrences in controllers (valid Py3.14)" "$except_count" "4"
assert_eq "CONVENTIONS.md gotcha documents the except A, B form" \
    "$(grep -c 'except A, B' "$DOC/CONVENTIONS.md")" "1"

# MAKE_UPDATE 8-queue flush order (verified against store.js).
queue_clears=$(grep -cE '_QUEUE\.clear\(\)' "$MAIL/static/src/model/store.js")
assert_eq "store.js has all 8 flush queues (.clear() calls)" "$queue_clears" "8"

# ============================ TEST_TAGS ============================
assert_eq "test_mail_hardening_v6.py is gone (deleted in e4df7f5569b)" \
    "$([ -f "$MAIL/tests/test_mail_hardening_v6.py" ] && echo 1 || echo 0)" "0"
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
# Both 0-byte ir_binary.py placeholders are now deleted outright. Round 3 measured their
# byte count, which is a file-exists assertion in disguise -- it fails loudly once they go.
assert_eq "models/ir_binary.py is deleted" \
    "$([ -e "$MAIL/models/ir_binary.py" ] && echo 1 || echo 0)" "0"
assert_eq "models/discuss/ir_binary.py is deleted" \
    "$([ -e "$MAIL/models/discuss/ir_binary.py" ] && echo 1 || echo 0)" "0"
assert_eq "ir_binary not imported in models/__init__.py" \
    "$(grep -c 'ir_binary' "$MAIL/models/__init__.py")" "0"
assert_eq "ir_binary not imported in models/discuss/__init__.py" \
    "$(grep -c 'ir_binary' "$MAIL/models/discuss/__init__.py")" "0"

# Gateway partner/user finders are on mail_thread.py, not base.py.
assert_eq "_mail_find_user_for_gateway is on mixin_mail_thread.py" \
    "$(grep -c 'def _mail_find_user_for_gateway' "$MAIL/models/mixin_mail_thread.py")" "1"
assert_eq "_mail_find_user_for_gateway is NOT on base.py" \
    "$(grep -c 'def _mail_find_user_for_gateway' "$MAIL/models/base.py")" "0"

# mail.thread class-level knob defaults.
assert_eq "_mail_flat_thread default is True" \
    "$(grep -c '_mail_flat_thread = True' "$MAIL/models/mixin_mail_thread.py")" "1"
assert_eq "_mail_thread_customer default is False" \
    "$(grep -c '_mail_thread_customer = False' "$MAIL/models/mixin_mail_thread.py")" "1"
assert_eq "_mail_post_access default is write" \
    "$(grep -c '_mail_post_access = "write"' "$MAIL/models/mixin_mail_thread.py")" "1"
assert_eq "_primary_email default is email" \
    "$(grep -c '_primary_email = "email"' "$MAIL/models/mixin_mail_thread.py")" "1"

# Directory-map corrected counts.
assert_eq "views/ recursive JS count is 61" \
    "$(find "$MAIL/static/src/views" -name '*.js' -not -path '*/@types/*' | wc -l)" "61"
assert_eq "DIRECTORY_MAP.md cites views 61" \
    "$(grep -cE '`views/` \| 61 \|' "$DOC/DIRECTORY_MAP.md")" "1"
assert_eq "DIRECTORY_MAP.md no stale views ~35 cite" \
    "$(grep -c '~35' "$DOC/DIRECTORY_MAP.md")" "0"
# static/src/js/ was the last unlayered directory and was retired in 9437c1915df. Round 3
# asserted it held 13 files; the directory is gone and its four DIRECTORY_MAP rows with it.
assert_eq "static/src/js/ is retired (directory absent)" \
    "$([ -d "$MAIL/static/src/js" ] && echo 1 || echo 0)" "0"
assert_eq "nothing imports @mail/js/" \
    "$(grep -rl '@mail/js/' --include='*.js' "$MAIL/static" 2>/dev/null | wc -l)" "0"
assert_eq "DIRECTORY_MAP.md records the js/ retirement" \
    "$(grep -c '`js/` no longer exists' "$DOC/DIRECTORY_MAP.md")" "1"
assert_eq "rotting widgets landed in views/web/rotting/" \
    "$(find "$MAIL/static/src/views/web/rotting" -name '*.js' | wc -l)" "9"
assert_eq "emojis_mixin landed in utils/web/" \
    "$([ -f "$MAIL/static/src/utils/web/emojis_mixin.js" ] && echo 1 || echo 0)" "1"
assert_eq "ASSET_LAYERS.md lists the utils/web layer dir" \
    "$(grep -c 'utils/{common,web}' "$DOC/ASSET_LAYERS.md")" "1"
assert_eq "mock_models file count is 35" \
    "$(find "$MAIL/static/tests/mock_server/mock_models" -name '*.js' | wc -l)" "35"
assert_eq "TEST_TAGS.md cites 35 mock model files" \
    "$(grep -c '35 mock model files' "$DOC/TEST_TAGS.md")" "1"
assert_eq "wizard .py files (excl __init__) is 9" \
    "$(find "$MAIL/wizard" -name '*.py' ! -name '__init__.py' | wc -l)" "9"

# ROUTE_MAP: two channel.py routes require login (update_avatar + sub_channel/delete).
# The literal said 1 while the line above it said two, so this could never pass.
assert_eq "channel.py's two auth=user routes (update_avatar + sub_channel/delete)" \
    "$(grep -c 'auth="user"' "$MAIL/controllers/discuss/channel.py")" "2"

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
assert_eq "mail_mock_server.js registers 40 routes" \
    "$(grep -cE '^registerRoute\(' "$MAIL/static/tests/mock_server/mail_mock_server.js")" "40"
assert_eq "TEST_TAGS.md cites 40 mocked RPC routes (not ~52)" \
    "$(grep -c '40 mocked RPC routes' "$DOC/TEST_TAGS.md")" "1"
assert_eq "TEST_TAGS.md no stale ~52 cite" \
    "$(grep -c '~52' "$DOC/TEST_TAGS.md")" "0"

# JS test directory table. core/ was cited as 15 (really 16) and widgets/ as 2 (really 1);
# the two errors cancelled, so the table summed correctly while both rows were wrong.
assert_eq "static/tests/core/ test files"    "$(find "$MAIL/static/tests/core"    -name '*.test.js' | wc -l)" "22"
assert_eq "static/tests/widgets/ test files" "$(find "$MAIL/static/tests/widgets" -name '*.test.js' | wc -l)" "1"
assert_eq "static/tests/discuss/ test files" "$(find "$MAIL/static/tests/discuss" -name '*.test.js' | wc -l)" "45"
assert_eq "static/tests/composer/ test files" "$(find "$MAIL/static/tests/composer" -name '*.test.js' | wc -l)" "5"
assert_eq "static/tests/message/ test files"  "$(find "$MAIL/static/tests/message"  -name '*.test.js' | wc -l)" "4"
assert_eq "TEST_TAGS.md cites discuss/ 44" "$(grep -c '| `discuss/` | 44 |' "$DOC/TEST_TAGS.md")" "1"
# The JS table's rows must still account for every *.test.js file. Round 3 shipped two rows
# wrong whose errors cancelled, so the sum looked right -- assert the sum against reality.
assert_eq "TEST_TAGS.md JS table row total matches reality" \
    "$(grep -c 'Rows below sum to 142' "$DOC/TEST_TAGS.md")" "1"
assert_eq "TEST_TAGS.md cites core/ 22" \
    "$(grep -c '| `core/` | 22 |' "$DOC/TEST_TAGS.md")" "1"
assert_eq "TEST_TAGS.md moved widgets/ to the '1 each' row" \
    "$(grep -c 'translation/`, `widgets/`' "$DOC/TEST_TAGS.md")" "1"

# Test-class tagging. Both @tagged and @odoo.tests.tagged spellings are in use; counting only
# the bare form undercounts (that is how "97 post_install classes" was reached).
tagged_total=$(grep -rhcE '^@(odoo\.tests\.)?tagged\(' "$MAIL/tests" | awk '{s+=$1} END{print s}')
tagged_post=$(grep -rhE '^@(odoo\.tests\.)?tagged\(' "$MAIL/tests" | grep -c 'post_install')
assert_eq "tagged test classes (both decorator spellings)" "$tagged_total" "76"
assert_eq "tagged classes carrying post_install" "$tagged_post" "60"
assert_eq "TEST_TAGS.md cites 56 of 72" \
    "$(grep -c 'Of \*\*72\*\* tagged classes, \*\*56\*\*' "$DOC/TEST_TAGS.md")" "1"
assert_eq "TEST_TAGS.md warns about the two decorator spellings" \
    "$(grep -c 'decorator spellings are in use' "$DOC/TEST_TAGS.md")" "1"

# Per-tag class counts that the docs assert in prose.
# The twenty-one round-numbered hardening/audit suites were deleted in e4df7f5569b. Round 3
# asserted one of them existed; assert the opposite, so a reintroduction is caught rather than
# a deletion. A tag that selects nothing reports SUCCESS having run no test -- the failure mode
# worth guarding.
assert_eq "no round-numbered hardening/audit suite files remain" \
    "$(find "$MAIL/tests" -name 'test_mail_hardening_v*.py' -o -name 'test_mail_audit_v*.py' | wc -l)" "0"
assert_eq "no mail_hardening_* tag is still declared" \
    "$(grep -rhE '^@(odoo\.tests\.)?tagged\(' "$MAIL/tests" | grep -c 'mail_hardening')" "0"
assert_eq "no doc still routes readers to a mail_hardening_v* run" \
    "$(grep -c 'test-tags mail_hardening' "$DOC"/*.md | grep -vc ':0')" "0"
assert_eq "the parity pin that replaced them exists" \
    "$([ -f "$MAIL/tests/test_mail_message_access_parity.py" ] && echo 1 || echo 0)" "1"
assert_eq "TEST_TAGS.md records the deletion" \
    "$(grep -c 'round-numbered hardening suites are gone' "$DOC/TEST_TAGS.md")" "1"
assert_eq "mail_controller classes (7 across 6 discuss files + mock_server_contract)" \
    "$(grep -rhE '^@(odoo\.tests\.)?tagged\(' "$MAIL/tests" | grep -c 'mail_controller')" "9"

# Controller file count: 19, not 21 — the docs were counting the two __init__.py, which is
# inconsistent with the models row (76, which excludes it).
assert_eq "controller files (excl __init__)" \
    "$(find "$MAIL/controllers" -name '*.py' ! -name '__init__.py' | wc -l)" "20"
assert_eq "ROUTE_MAP.md cites 20 controller files" \
    "$(grep -c '\*\*20\*\* controller files' "$DOC/ROUTE_MAP.md")" "1"
assert_eq "no doc still claims 19 or 21 controller files" \
    "$(grep -rcE '(19|21) controller files' "$DOC"/*.md | grep -vc ':0')" "0"
assert_eq "ARCHITECTURE.md cites 20 controller files and 64 routes" \
    "$(grep -c '| 20 files · \*\*64\*\* routes across \*\*84\*\* URL strings |' "$DOC/ARCHITECTURE.md")" "1"
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

# ================= Round-4 fact-check: previously uncovered claims =================
# Everything below was wrong or unguarded in round 3.

# The renamed helper families. Each old name is a method an override can still be WRITTEN
# against -- it compiles, overrides nothing, and raises nothing -- so assert both that the new
# name exists AND that the old one does not, in the code and in the docs.
assert_eq "base.py: _message_get_suggested_recipients_sources (was _message_add_...)" \
    "$(grep -cE 'def _message_get_suggested_recipients_sources\(' "$MAIL/models/base.py")" "1"
assert_eq "base.py: _message_get_default_recipients_sources exists" \
    "$(grep -cE 'def _message_get_default_recipients_sources\(' "$MAIL/models/base.py")" "1"
assert_eq "_message_add_suggested_recipients is gone module-wide" \
    "$(grep -rE 'def _message_add_suggested_recipients\(' "$MAIL" --include='*.py' | wc -l)" "0"
assert_eq "the one _add_ helper that mutates in place kept its verb" \
    "$(grep -cE 'def _message_add_suggested_recipients_from_replies\(' "$MAIL/models/base.py")" "1"
assert_eq "mixin.mail.thread.cc overrides the _sources hook, not the _add_ one" \
    "$(grep -cE 'def _message_get_suggested_recipients_sources\(' "$MAIL/models/mixin_mail_thread_cc.py")" "1"
assert_eq "no doc names _message_add_suggested_recipients as the hook" \
    "$(grep -c 'overrides `_message_add_suggested_recipients`' "$DOC"/*.md | grep -vc ':0')" "0"

# _partner_find_from_emails is on base.py. MODEL_MAP.md asserted the opposite in prose --
# "on mail_thread.py, not base.py" -- while CONVENTIONS.md had it right, so the two docs
# contradicted each other and nothing caught it. Pin the location and both docs.
assert_eq "_partner_find_from_emails is on base.py" \
    "$(grep -cE 'def _partner_find_from_emails\(' "$MAIL/models/base.py")" "1"
assert_eq "_partner_find_from_emails is NOT on mixin_mail_thread.py" \
    "$(grep -cE 'def _partner_find_from_emails\(' "$MAIL/models/mixin_mail_thread.py")" "0"
assert_eq "no doc claims _partner_find_from_emails lives on the thread mixin" \
    "$(grep -c 'finders `_partner_find_from_emails`' "$DOC"/*.md | grep -vc ':0')" "0"

# mail.followers: _insert_followers -> _add_followers, and the OLD _add_followers (which
# returned payloads) -> _prepare_followers_vals. The name _add_followers therefore exists on
# both sides of the rename meaning different things -- a carried-over call site compiles.
assert_eq "mail.followers._add_followers creates the records" \
    "$(grep -cE 'def _add_followers\(' "$MAIL/models/mail_followers.py")" "1"
assert_eq "mail.followers._prepare_followers_vals builds the vals" \
    "$(grep -cE 'def _prepare_followers_vals\(' "$MAIL/models/mail_followers.py")" "1"
assert_eq "_insert_followers is gone (SQL DML verb, ORM create)" \
    "$(grep -rE 'def _insert_followers\(' "$MAIL" --include='*.py' | wc -l)" "0"
# name/email were deleted: related+related_sudo leaked past the res.partner ACL to every
# internal user, and rode the chatter payload. is_active and display_name stay.
assert_eq "mail.followers no longer exposes name/email related fields" \
    "$(grep -cE '^ *(name|email) = fields\.' "$MAIL/models/mail_followers.py")" "0"
assert_eq "mail.followers keeps is_active" \
    "$(grep -c 'is_active = fields.Boolean' "$MAIL/models/mail_followers.py")" "1"
assert_eq "MODEL_MAP.md no longer lists name/email on mail.followers" \
    "$(grep -c '`name`/`email`/`is_active` (related)' "$DOC/MODEL_MAP.md")" "0"

# mail.template: the four _generate_template* builders are _prepare_* under 2.4.
assert_eq "_generate_template* is gone from mail.template" \
    "$(grep -cE 'def _generate_template' "$MAIL/models/mail_template.py")" "0"
assert_eq "mail.template _prepare_mail_vals exists" \
    "$(grep -cE 'def _prepare_mail_vals\(' "$MAIL/models/mail_template.py")" "1"
assert_eq "mail.template _prepare_recipient_vals exists" \
    "$(grep -cE 'def _prepare_recipient_vals\(' "$MAIL/models/mail_template.py")" "1"
assert_eq "MODEL_MAP.md no stale _generate_template cite" \
    "$(grep -c '_generate_template(res_ids, fields)' "$DOC/MODEL_MAP.md")" "0"

# mail.message is split across three files; MODEL_MAP attributed all of it to mail_message.py.
assert_eq "mail_message_access.py holds the access rule" \
    "$(grep -cE 'def _get_forbidden_access\(' "$MAIL/models/mail_message_access.py")" "1"
assert_eq "mail_message_store.py holds _to_store" \
    "$(grep -cE 'def _to_store\(' "$MAIL/models/mail_message_store.py")" "1"
assert_eq "_check_access moved off mail_message.py" \
    "$(grep -cE 'def _check_access\(' "$MAIL/models/mail_message.py")" "0"
# 3x each: the section-1 data-model row, the three-files note, and the model index.
assert_eq "MODEL_MAP.md lists mail_message_access.py" \
    "$(grep -c 'mail_message_access.py' "$DOC/MODEL_MAP.md")" "3"
assert_eq "MODEL_MAP.md lists mail_message_store.py" \
    "$(grep -c 'mail_message_store.py' "$DOC/MODEL_MAP.md")" "3"
assert_eq "the parity pin holding the rule's two spellings exists" \
    "$(grep -c '^class TestMailMessageAccessParity' "$MAIL/tests/test_mail_message_access_parity.py")" "1"

# Restricted rendering is a parsed-tree walk now, not a regex. _render_regex_resolve is gone;
# the root allow-list (object, user) it enforced is what actually matters, so pin that.
assert_eq "_render_regex_resolve is gone" \
    "$(grep -rE 'def _render_regex_resolve\(' "$MAIL" --include='*.py' | wc -l)" "0"
assert_eq "_resolve_static_expression replaces it" \
    "$(grep -cE 'def _resolve_static_expression\(' "$MAIL/models/mixin_mail_render.py")" "1"
assert_eq "it accepts root 'object'" \
    "$(grep -c 'if root == "object":' "$MAIL/models/mixin_mail_render.py")" "1"
assert_eq "it accepts root 'user'" \
    "$(grep -c 'elif root == "user":' "$MAIL/models/mixin_mail_render.py")" "1"
assert_eq "an unknown root is refused, not guessed" \
    "$(grep -c 'Unsupported root' "$MAIL/models/mixin_mail_render.py")" "1"
assert_eq "the allow-list itself is still on base.py" \
    "$(grep -cE 'def mail_allowed_qweb_expressions\(' "$MAIL/models/base.py")" "1"
assert_eq "CONVENTIONS.md gotcha 8 names the current helper" \
    "$(grep -c '_resolve_static_expression' "$DOC/CONVENTIONS.md")" "1"

# ASSET_LAYERS cited a formatters.js path that does not exist. Pin the manifest string.
assert_eq "mail.assets_public re-includes web/static/src/core/formatters.js" \
    "$(grep -c '"web/static/src/core/formatters.js"' "$MAIL/__manifest__.py")" "1"
assert_eq "no such file as web/static/src/fields/formatters.js" \
    "$([ -e "$ODOO/addons/web/static/src/fields/formatters.js" ] && echo 1 || echo 0)" "0"
assert_eq "ASSET_LAYERS.md cites the core/ formatters path" \
    "$(grep -c 'web/static/src/core/formatters.js' "$DOC/ASSET_LAYERS.md")" "1"

# Layer gate: ASSET_LAYERS claims it is drift-zero with an empty KNOWN_VIOLATIONS.
assert_eq "js_deployment_layers.py gate exists" \
    "$([ -f "$ODOO/tooling/architecture/js_deployment_layers.py" ] && echo 1 || echo 0)" "1"
assert_eq "KNOWN_VIOLATIONS is empty" \
    "$(grep -c 'KNOWN_VIOLATIONS: tuple\[Known, ...\] = ()' "$ODOO/tooling/architecture/js_deployment_layers.py")" "1"
assert_eq "the gate is wired into architecture.yml" \
    "$(grep -c 'js_deployment_layers.py --check' "$ODOO/.github/workflows/architecture.yml")" "1"

# Per-subtree JS counts DIRECTORY_MAP states. Round 3 pinned only views/ and js/, so core/,
# discuss/ and utils/ drifted unnoticed.
assert_eq "core/ recursive JS count"    "$(find "$MAIL/static/src/core"    -name '*.js' | wc -l)" "153"
assert_eq "discuss/ recursive JS count" "$(find "$MAIL/static/src/discuss" -name '*.js' | wc -l)" "146"
assert_eq "utils/ recursive JS count"   "$(find "$MAIL/static/src/utils"   -name '*.js' | wc -l)" "10"
assert_eq "chatter/ recursive JS count" "$(find "$MAIL/static/src/chatter" -name '*.js' | wc -l)" "13"
assert_eq "DIRECTORY_MAP.md cites core 153"    "$(grep -c '| `core/` | 153 |' "$DOC/DIRECTORY_MAP.md")" "1"
assert_eq "DIRECTORY_MAP.md cites discuss 146" "$(grep -c '| `discuss/` | 146 |' "$DOC/DIRECTORY_MAP.md")" "1"

# SCSS count: stated in ARCHITECTURE's table, never asserted.
assert_eq "static/src SCSS count" "$(find "$MAIL/static/src" -name '*.scss' | wc -l)" "101"
assert_eq "ARCHITECTURE.md cites 101 SCSS" \
    "$(grep -c '| SCSS (`static/src/`) | 101 |' "$DOC/ARCHITECTURE.md")" "1"

# tools/ file list, stated in DIRECTORY_MAP and two files short.
assert_eq "tools/ .py count (excl __init__)" \
    "$(find "$MAIL/tools" -maxdepth 1 -name '*.py' ! -name '__init__.py' | wc -l)" "10"
for t in access_scan channel_avatar; do
    assert_eq "DIRECTORY_MAP.md lists tools/$t.py" \
        "$(grep -c "\`$t.py\`" "$DOC/DIRECTORY_MAP.md")" "1"
done

# Doc-set hygiene: no doc may spell the module path as if the checkout were nested.
assert_eq "no doc spells the module addons/odoo/addons/mail" \
    "$(grep -c 'addons/odoo/addons/mail' "$DOC"/*.md | grep -vc ':0')" "0"

# TEST_TAGS' run commands must name paths that exist in this workspace.
assert_eq "TEST_TAGS.md no stale config/p314o19marin.conf path" \
    "$(grep -c 'config/p314o19marin.conf' "$DOC/TEST_TAGS.md")" "0"
assert_eq "TEST_TAGS.md no stale venv/ interpreter path" \
    "$(grep -c 'venv/p314o19marin/bin/python' "$DOC/TEST_TAGS.md")" "0"

# Untagged test files: TEST_TAGS states 28 of 52 are unreachable by --test-tags.
untagged=$(python3 - "$MAIL" <<'PYEOF'
import ast, pathlib, sys
root = pathlib.Path(sys.argv[1], "tests")
SKIP = {"post_install", "-at_install", "at_install", "standard", "-standard"}
tagged, allf = set(), {p for p in root.rglob("test_*.py")}
for p in root.rglob("*.py"):
    for cls in (n for n in ast.walk(ast.parse(p.read_text())) if isinstance(n, ast.ClassDef)):
        for d in cls.decorator_list:
            if isinstance(d, ast.Call) and ast.unparse(d.func).endswith("tagged"):
                if any(ast.literal_eval(a) not in SKIP
                       for a in d.args if isinstance(a, ast.Constant)):
                    tagged.add(p)
print(len(allf - tagged))
PYEOF
)
assert_eq "test files reachable only by the module filter" "$untagged" "30"
assert_eq "TEST_TAGS.md cites 30 of 55 untagged" \
    "$(grep -c '30 of the 55 test files carry no topic tag' "$DOC/TEST_TAGS.md")" "1"

# ============================ Doc set completeness ============================
for f in ARCHITECTURE CONVENTIONS DIRECTORY_MAP MODEL_MAP ROUTE_MAP STATE_MANAGEMENT TEST_TAGS ASSET_LAYERS; do
    assert_eq "$f.md exists" "$([ -f "$DOC/$f.md" ] && echo 1 || echo 0)" "1"
done

echo ""
echo "================================================================"
echo "TOTAL: $PASS passed, $FAIL failed (round 4 — 2026-08-17)"
echo "================================================================"
exit $FAIL
