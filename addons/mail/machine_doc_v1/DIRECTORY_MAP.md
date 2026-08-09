# Directory Map

Maps each `static/src/` directory of the `mail` module → its **layer** (deployment context,
see `ASSET_LAYERS.md`) + primary responsibility. JS file counts are per-directory
(non-recursive), excluding `@types/`.

> Layer suffixes: `common` (everywhere incl. public page) · `web` (backend) · `public_web`
> (backend + public page) · `web_portal` (portal + backend) · `public` (public page only).
> See `ASSET_LAYERS.md` for how the suffix decides bundle membership.

## Top-level split

| Subtree | JS files | What |
|---------|---------:|------|
| `model/` | 10 | The client-side reactive ORM (`Record`/`Store`) — see `STATE_MANAGEMENT.md` |
| `core/` | 149 | The messaging framework: store service, models, base UI components |
| `discuss/` | 144 | The Discuss app feature layers (channels, calls, typing, voice, gifs, pinning) |
| `chatter/` | 13 | Form/portal document chatter |
| `views/` | 50 | Backend view integrations (activity views, mail field widgets) |
| `utils/` | 9 | Shared date/format/DOM helpers |
| `js/` | 13 | Legacy-style widgets (rotting kanban, tours, debug menu) |
| `webclient/` | 1 | Webclient-level wiring |
| `worklets/` | 1 | `audio_processor.js` — the RTC audio worklet, served raw by `/mail/rtc/audio_worklet_processor_v2` (not bundled) |
| `(root)` | 2 | `service_worker.js` + `service_worker_utils.js` |

The rows above sum to **392**, the module's full `static/src` JS count. (`audio/`, `img/`
and `scss/` carry no JS.)

## `model/` — the reactive ORM (layer: bundled everywhere)

| Directory | Files | Responsibility |
|-----------|------:|----------------|
| `model/` | 10 | `Record`, `Store`, `RecordList`, `RecordUses`, the `*_internal` engines, `make_store`, `misc` (registry + `fields` factory). See `STATE_MANAGEMENT.md` |

## `core/` — messaging framework

| Directory | Layer | Files | Responsibility |
|-----------|-------|------:|----------------|
| `core/common/` | common | 92 | Store service, the 30 core JS models (Thread, Message, Attachment, Composer, Follower, Notification, Activity, personas…) — 31 `.register()` calls counting the `Store` singleton itself — base components (composer, message, thread, chat window/hub, attachment views), core services |
| `core/common/plugin/` | common | 3 | html_editor plugins for the composer |
| `core/public_web/` | public_web | 13 | `DiscussClientAction`, the `Discuss` app UI, `MessagingMenu`, `DiscussApp` model — shared by backend + public page |
| `core/web/` | web | 40 | Backend-only: activity UI (menu, list popover, mark-as-done), follower list, backend chatter wiring, command palette, systray patches |
| `core/web_portal/` | web_portal | 1 | Portal+backend shared core |

## `discuss/` — the Discuss app

| Directory | Layer | Files | Responsibility |
|-----------|-------|------:|----------------|
| `discuss/core/common/` | common | 23 | Channel model patches, `discuss.core.common` service (channel bus subscriptions), sub-channels, member list |
| `discuss/core/public/` | public | 7 | Public-page boot (`boot.js`), welcome screen, public-only patches |
| `discuss/core/public_web/` | public_web | 19 | Sidebar, channel categories, `discuss.core.public.web` service, bus connection alert |
| `discuss/core/web/` | web | 11 | Backend Discuss integration, `discuss.core.web` service |
| `discuss/call/common/` | common | 44 | The RTC engine: `discuss.rtc` service, P2P layer, call invitations, PiP, push-to-talk, `RtcSession` model, call UI |
| `discuss/call/public/` | public | 2 | Public-page call bootstrapping |
| `discuss/call/public_web/` | public_web | 5 | Shared call UI |
| `discuss/call/web/` | web | 3 | Backend call integration |
| `discuss/typing/common/` | common | 5 | "X is typing…" indicator + service |
| `discuss/voice_message/common/` | common | 11 | Voice-message recording/playback service, `VoiceMetadata` model |
| `discuss/voice_message/worklets/` | — | 1 | Audio worklet processor (served as raw JS) |
| `discuss/message_pin/common/` | common | 7 | Message pinning |
| `discuss/gif_picker/common/` | common | 4 | Tenor GIF picker |
| `discuss/web/` | web | 1 | Backend-only discuss glue |
| `discuss/web/avatar_card/` | web | 1 | Avatar hover-card popover |

## `chatter/` — document chatter

| Directory | Layer | Files | Responsibility |
|-----------|-------|------:|----------------|
| `chatter/web/` | web | 10 | Backend chatter: scheduled-message model, chatter container patches |
| `chatter/web_portal/` | web_portal | 3 | The `Chatter` component (form-view + portal) — shipped standalone as `mail.assets_chatter_web_portal` |

## `views/` — backend view integrations (layer: web)

Unlike the tables above, these rows are **recursive** (each widget lives in its own
subdirectory); they sum to the subtree's 50 files.

| Directory | Files | Responsibility |
|-----------|------:|----------------|
| `views/web/activity/` | 8 | The Activity view type (calendar-like activity board) |
| `views/web/calendar/` (+ `calendar_common`, `calendar_year`) | 6 | Calendar-view mail integration |
| `views/web/fields/` | ~24 | Mail field widgets: avatar (user), `many2one_avatar_user`, `many2many_tags_email`, emojis char/text, html-composer/mail fields, kanban/list activity, scheduled-date, activity-exception, properties |
| `views/web/kanban/`, `views/web/list/`, `views/web/model/`, `views/web/view_dialog/` | ~7 | Kanban/list activity columns, model helpers, view dialogs |
| `views/fields/` (activity_model_selector, badge_selection_icons, mail_server_configurator_selection, statusbar_duration) | 4 | Backend config field widgets |

## `utils/` , `js/` , `webclient/`

| Directory | Layer | Files | Responsibility |
|-----------|-------|------:|----------------|
| `utils/common/` | common | 9 | `format.js`, `dates.js`, `hooks.js`, `misc.js`, `counters.js`, `media_monitoring.js`, `pdf_thumbnail.js`, `composer_insert.js`, `thread_read.js` |
| `js/rotting_mixin/` | web | 9 | "Rotting" kanban/statusbar widgets (stale-record highlighting) driven by `mail.tracking.duration.mixin` |
| `js/tools/` | web | 1 | Debug-menu items |
| `js/tours/` | — | 1 | Backend discuss tour |
| `js/` (root) | web | 2 | `onchange_on_keydown.js`, `emojis_mixin.js` |
| `webclient/web/` | web | 1 | Webclient-level mail wiring |

## `scss/` (styles only, no JS)

| Directory | What |
|-----------|------|
| `scss/` | Shared mail SCSS (variables, base styles) |
| `scss/variables/` | `primary_variables.scss` (→ `web._assets_primary_variables`) + `derived_variables.scss` |

> Component SCSS is **co-located** with its `.js`/`.xml` trio (e.g.
> `core/common/composer.{js,xml,scss}`), following the same OWL-trio convention as
> the web module. There are no `*.dark.scss` files left in mail: `web` now answers
> both colour schemes from one stylesheet (see `ASSET_LAYERS.md`).

## Non-JS directories (module root)

| Directory | What |
|-----------|------|
| `models/` (+ `models/discuss/`) | 76 Python model files — see `MODEL_MAP.md` |
| `controllers/` (+ `controllers/discuss/`) | 19 controller files, 65 routes — see `ROUTE_MAP.md` |
| `wizard/` | 9 wizard `.py` files (composer, activity schedule + summary, blacklist remove, followers edit, template preview/reset, + 2 `_inherit` hooks) |
| `tools/` | Pure-Python helpers: `discuss.py` (guest context), `jwt.py`, `link_preview.py`, `mail_validation.py`, `parser.py`, `web_push.py`, `alias_error.py` |
| `data/` | 15 XML data files (subtypes, activity types, templates, channels, crons) |
| `demo/` | 4 demo XML files |
| `views/` | 41 backend view XML files |
| `security/` | `ir.model.access.csv` + `mail_security.xml` |
| `migrations/` | `19.0.1.20/post-migration.py`, `19.0.1.21/pre-migration.py` |
| `static/lib/` | Vendored libs: idb-keyval, lame, odoo_sfu, selfie_segmentation (see `ASSET_LAYERS.md`) |
| `static/tests/` | 128 HOOT `*.test.js` + helpers + tours — see `TEST_TAGS.md` |
| `push-to-talk-extension/` | Browser extension source for the push-to-talk feature |
