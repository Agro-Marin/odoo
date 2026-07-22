# Mail Module Test Tags

Reference for running targeted subsets of the `mail` module's tests — Python
(`tests/`, 58 `test_*.py` files) and JavaScript HOOT (`static/tests/`, 127 `*.test.js`).

> **See also**: `CONVENTIONS.md` (the mock-gateway / bus test helpers), `ROUTE_MAP.md`
> (the controller-contract tests), `STATE_MANAGEMENT.md` (what the JS store tests exercise).

## Python — how mail tests are tagged

Almost every mail test class is decorated `@tagged("post_install", "-at_install", …)` — the
suites need a fully-installed database (mail wires into `res.partner`, `res.users`, the bus,
etc.). **97** classes carry `post_install`/`-at_install`. Topic tags on top of that are
**sparse** — many files carry only the install-phase tags and are selected by the module
filter (`-u mail`) alone, not by a topic tag.

### Topic tags → files

| Tag | Files | Covers |
|-----|-------|--------|
| `mail_hardening_v6` (14 classes) | `test_mail_hardening_v6.py` | Fork security/hardening regression suite v6 |
| `mail_hardening_v7` (4) | `test_mail_hardening_v7.py` | Hardening v7 |
| `mail_hardening_v8` (1) | `test_mail_hardening_v8.py` | Hardening v8 |
| `mail_hardening_v9` (7) | `test_mail_hardening_v9.py` | Hardening v9 |
| `mail_hardening_v10` (3) | `test_mail_hardening_v10.py` | Hardening v10 |
| `mail_hardening_v11` (3) | `test_mail_hardening_v11.py` | Hardening v11: `/mail/data` fetch-param isolation, dynamic-model-name guards, controller id coercion, inbox fan-out cost |
| `mail_controller` (7) | `test_mock_server_contract.py`, `discuss/test_*_controller.py` (message, reaction, binary, message_update, thread, attachment) | HTTP controller ↔ store-payload contract |
| `mail_store_contract` | `test_mock_server_contract.py` | The JS-store ↔ server payload shape contract |
| `mail_tools` | `test_mail_tools.py`, `test_res_users.py`, `test_res_partner.py` | Email parsing/normalization helpers |
| `mail_init` | `test_mail_tools.py` | Module init / post-init hook |
| `mail_template` | `test_mail_template.py` | `mail.template` + `send_mail` |
| `mail_render`, `regex_render` | `test_mail_render.py` | QWeb / inline-template rendering |
| `mail_message` | `test_mail_message.py`, `test_mail_message_translate.py`, `test_link_preview.py`, `discuss/test_message_controller.py` | `mail.message` model + translation |
| `mail_link_preview` | `test_link_preview.py` | URL link-preview generation |
| `mail_composer` | `test_mail_composer.py` | `mail.compose.message` wizard |
| `mail_activity` | `test_mail_activity.py` | `mail.activity` scheduling/state |
| `mail_server` | `test_ir_mail_server.py` | Outgoing SMTP server selection/config |
| `mail_thread`, `mail_thread_api` | `test_ir_ui_menu.py`, `test_res_partner.py` | `mail.thread` integration / API |
| `res_users`, `res_partner` | `test_res_users.py`, `test_res_partner.py`, `test_mail_tools.py` | Partner/user mail behavior |
| `mail_js` | `test_js.py` | Runs the JS/HOOT suites in a headless browser |
| `discuss_action` | `discuss/test_discuss_action.py` | Discuss client-action loading |
| `RTC` | `discuss/test_rtc.py` | WebRTC call session model |
| `is_tour` | `discuss/test_discuss_channel_as_guest.py` | Guest browser tours |

> **Fork hardening/audit suites without a topic tag.** `test_mail_hardening_v2.py` …
> `_v5.py` and `test_mail_audit_v6.py` / `_v6b.py` carry only `("post_install",
> "-at_install")`. They are the AgroMarin fork's own regression suites (upstream is the
> baseline, not the ceiling — see the fork memory) and run under the module filter, not a
> topic tag. `_v6` onwards (`_v6`…`_v11`) DID get dedicated tags; the earlier ones did not.

### Base test classes (`tests/common.py`)

The mail test tower — subclass `MailCommon` for almost everything:

| Class | Extends | Provides |
|-------|---------|----------|
| `MockEmail` | `BaseCase`, `MockSmtplibCase` | SMTP mocking foundation. `mock_mail_gateway(mail_unlink_sent=False)` ctx mgr (wraps `mail.mail` create/unlink), `mock_push_to_end_point`, `mock_datetime_and_now`. Assertions: `assertMailMail`, `assertMailMailWEmails/WRecord/WId`, `assertMessageFields`, `assertNoMail`, `assertSentEmail`/`assertNotSentEmail`, `assertPushNotification`/`assertNoPushNotification`, `assertTracking`, `assertHtmlEqual` |
| `MailCase` | `TransactionCase`, `MockEmail`, `BusCase` | Adds bus mocking (`mock_bus`), `mock_mail_app` (mocks `mail.message`/`mail.notification` create), `_reset_mail_context`. Assertions: `assertSinglePostNotifications`, `assertPostNotifications`, `assertBus`, `assertMailNotifications`, `assertBusNotifications`, `assertBusNotificationType`, `assertNotified`, `assertNoNotifications` |
| `MailCommon` | `MailCase` | Highest-level base; `setUpClass` provisions users / partners / templates. **The class most tests subclass.** |

Downstream bases: `MailControllerCommon(HttpCase, MailCommon)` and its children
(`MailControllerAttachmentCommon`, `MailControllerBinaryCommon`,
`MailControllerReactionCommon`, `MailControllerThreadCommon`, `MailControllerUpdateCommon`)
for controller-contract tests; `TestMailRenderCommon` for rendering; `MailTrackingDurationMixinCase`.

> The primary hooks are `mock_mail_gateway` (capture outgoing mail without SMTP),
> `mock_bus` (capture bus notifications), and `assertMailMail` (assert an outgoing
> `mail.mail`).

### Running Python tests

```bash
CONF=config/p314o19marin.conf
PY="venv/p314o19marin/bin/python addons/odoo/odoo-bin"

# A fork hardening suite:
$PY -c $CONF -d <db> --test-tags mail_hardening_v6 --stop-after-init --no-http

# Controller ↔ store contract:
$PY -c $CONF -d <db> --test-tags mail_controller --stop-after-init --no-http

# A single class/method:
$PY -c $CONF -d <db> --test-tags '/mail:TestMailActivity.test_activity_flow' --stop-after-init --no-http

# All mail tests (module filter; catches the topic-tag-less files):
$PY -c $CONF -d <db> -u mail --test-enable --stop-after-init --no-http
```

## JavaScript — HOOT suites (`static/tests/`)

127 `*.test.js` files. They run in a headless browser via `test_js.py` (tag `mail_js`), or
interactively at `/web/tests` (mail is included in `web.assets_unit_tests`).

### File groups (by subdirectory)

| Directory | Files | Scope |
|-----------|------:|-------|
| `discuss/` | 40 | Discuss app: channels, members, calls, sidebar, sub-channels |
| `core/` | 15 | Store/Record framework, personas, notifications, settings |
| `web/` | 9 | Backend-web integration (systray, form chatter wiring) |
| `chatter/` | 9 | Form-view chatter |
| `discuss_app/` | 6 | Discuss client-action shell |
| `thread/` | 5 | Thread rendering + message list |
| `utils/` | 5 | Date/format/misc helper units |
| `composer/` | 4 | Message composer |
| `activity/`, `message/`, `mock_server/` | 3 each | Activities · message component · mock-server units |
| `chat_window/`, `emoji/`, `inline/`, `messaging_menu/`, `views/`, `widgets/` | 2 each | — |
| `chat_bubble/`, `crosstab/`, `gif_picker/`, `html_editor/`, `messaging/`, `mobile/`, `quick_reaction_menu/`, `scheduled_message/`, `suggestion/`, `translation/` | 1 each | — |
| `(root)` | 4 | Cross-cutting suites + helpers |
| `tours/` | 0 | Browser tours — excluded from the unit bundle (ship in `web.assets_tests`) |

### JS test helpers

`static/tests/mail_test_helpers.js` is the central harness:

| Export | Role |
|--------|------|
| `defineMailModels()` | `defineModels(mailModels)` — installs all mock models for a suite |
| `mailModels` | Registry of the mock model set |
| `start(options)` | Boot a mail-enabled test env |
| `startServer()` | Create the mock server |
| `openDiscuss(activeId, {target})` | Mount the Discuss app on a channel/mailbox |
| `openFormView` / `openKanbanView` / `openListView` / `openView` | Mount a backend view with chatter |
| `onRpcBefore` / `onRpcAfter`, `registerArchs`, `patchUiSize` | RPC hooks / arches / responsive sizing |
| `listenStoreFetch` / `waitStoreFetch`, `STORE_FETCH_ROUTES = ["/mail/action","/mail/data"]` | Await the batched store fetches |
| `makeMockRtcNetwork`, `createVideoStream`, `mockGetMedia`, `patchBrowserNotification` | RTC / media / notification mocks |
| `setupChatHub` / `assertChatHub`, `prepareRegistriesWithCleanup`, `userContext` | Chat-hub + registry helpers |

Other helper files: `mail_test_helpers_contains.js` (DOM `contains`-style assertions),
`mail_shared_tests.js` (reusable test bodies),
`mock_server/mail_mock_server.js` (~52 mocked RPC routes),
`mock_server/mock_models/` (35 mock model files: `mail_thread.js`, `mail_message.js`,
`discuss_channel.js`, `discuss_channel_member.js`, `discuss_channel_rtc_session.js`,
`mail_activity.js`, `res_partner.js`, `mail_guest.js`, `mail_notification.js`,
`ir_websocket.js`, …).

### Running JS tests

```bash
# Full HOOT suite in a headless browser (slow):
$PY -c $CONF -d <db> --test-tags mail_js --stop-after-init

# Interactively: start the server and open
#   http://localhost:8069/web/tests  → filter to @mail suites
```
