# Mail Module Architecture

High-level structure, data flow, and layer organization for `addons/odoo/addons/mail`.

> **See also**: `MODEL_MAP.md` (Python models + the `mail.thread` mixin API),
> `STATE_MANAGEMENT.md` (the JS `Store`/`Record` reactive ORM), `ROUTE_MAP.md` (HTTP/RPC
> endpoints), `ASSET_LAYERS.md` (the common/web/public bundling), `CONVENTIONS.md`
> (patterns & gotchas), `TEST_TAGS.md` (test selection), `DIRECTORY_MAP.md` (per-directory map).

## Module Identity

- **Name:** Discuss (technical name: `mail`)
- **Category:** Productivity/Discuss · **`application: True`**
- **Depends:** `web_tour`, `html_editor` (transitively `web`, `bus`, `base`)
- **`post_init_hook`:** `_mail_post_init`
- **Two faces:** (1) a **framework** — the `mail.thread` / `mail.activity.mixin` mixins that
  give every business model a chatter, followers, tracking, and an email gateway; and (2) an
  **application** — Discuss (real-time chat, channels, calls) with its own JS client.

## Layer Diagram

```
                         ┌───────────────── Browser ─────────────────┐
                         │                                           │
   Backend webclient     │   Public discuss page      Portal page    │
   (web.assets_backend)  │   (mail.assets_public)   (mail.assets_*)  │
        │                │          │                     │          │
        └────────────────┴──────────┴─────────────────────┘          │
                         │  OWL components (chatter, Discuss app,     │
                         │  chat windows, messaging menu, call UI)    │
                         │                    │                       │
                         │        useService("mail.store")            │
                         │                    ▼                       │
                         │   ┌──────────────────────────────────┐     │
                         │   │  JS Store  (static/src/model/)   │     │
                         │   │  reactive Record graph, upsert   │     │
                         │   │  via store.insert(data)          │     │
                         │   └───────┬───────────────┬──────────┘     │
                         └───────────│───────────────│────────────────┘
                    POST /mail/data  │               │  bus (websocket)
                    POST /mail/action│               │  "mail.record/insert", …
                                     ▼               ▼
   ┌──────────────────────────────────────────────────────────────────────┐
   │  Python  (controllers → mail.thread / models → PostgreSQL + SMTP)     │
   │                                                                       │
   │  ┌──────────────┐   ┌───────────────────────┐   ┌──────────────────┐  │
   │  │ Controllers  │──▶│ mail.thread mixin      │──▶│ mail.message /   │  │
   │  │ webclient.py │   │  message_post()        │   │ mail.mail /      │  │
   │  │ thread.py    │   │  _notify_thread()      │   │ mail.followers / │  │
   │  │ discuss/*.py │   │  message_process()     │   │ mail.notification│  │
   │  └──────────────┘   │  _track_*() tracking   │   └──────────────────┘  │
   │                     └───────────┬────────────┘            │            │
   │                                 │ _bus_send(type, payload)│ SMTP send  │
   │                                 ▼                         ▼            │
   │                         bus.bus / websocket        ir.mail_server      │
   └──────────────────────────────────────────────────────────────────────┘
                                     ▲
                    incoming email → message_process() → message_new()/message_update()
                                     (mail gateway: fetchmail.server, mail.alias)
```

## The two data planes

Discuss deliberately splits data flow into a **fetch plane** and a **push plane**:

1. **Fetch plane (request/response)** — the JS store batches its needs and POSTs to one of
   two endpoints (`controllers/webclient.py`):
   - `/mail/data` — **read-only** batched fetch (routed to a replica when configured)
   - `/mail/action` — batched fetch **with side effects**
   The server returns `{model_name: [rows]}`; the store does `store.insert(data)`. Named
   fetch params (`init_messaging`, `channels_as_member`, `discuss.channel`, …) are dispatched
   *inside* these two routes, not as separate URLs. See `ROUTE_MAP.md`.

2. **Push plane (bus/websocket)** — the server pushes live updates over the `bus` websocket.
   Python calls `record._bus_send("<model>/<verb>", payload)`; the JS services subscribe and
   feed the payload into the same `store.insert(...)`. The generic channel is
   **`mail.record/insert`**. See `STATE_MANAGEMENT.md`.

Both planes converge on the **single idempotent write path**: `store.insert()`. This is why
the client can merge an initial page payload, a batched fetch, and a live bus push without
divergence — every one is an upsert keyed by model id.

## Python side — the mixin framework

`mail` is mostly **abstract mixins** injected into other models (see `MODEL_MAP.md`). The
key contract:

- A business model adds `mail.thread` (± `mail.activity.mixin`) to `_inherit` and gains
  `message_ids`, `message_follower_ids`, activities, tracking, and the email gateway.
- **`message_post(**kwargs)`** (`mail_thread.py`) is the canonical posting entry point.
  Everything (chatter UI, templates, gateway) funnels through it → creates a `mail.message`
  → `_notify_thread()` fans out to inbox / email / web-push recipients.
- **Field tracking** — `write()` on a tracked model runs `_track_*` hooks that diff old/new
  values, create `mail.tracking.value` rows, and post a tracking message with the right
  subtype.
- **Incoming gateway** — `fetchmail.server` polls POP/IMAP; `message_process()` routes the
  email via `mail.alias` to `message_new()` (create a record) or `message_update()` (append
  to an existing thread); bounces and loops are detected along the way.

## JS side — the Discuss client

The client is a graph of `Record` instances in one long-lived reactive `Store` (unlike the
webclient's view-scoped `RelationalModel`). See `STATE_MANAGEMENT.md`. Highlights:

- **The store service** `mail.store` (`core/common/store_service.js`) owns the singleton,
  seeds it from `session.storeData` (backend) or `odoo.discuss_data` (public page), and
  drives the fetch plane.
- **~22 OWL services** provide behavior: `mail.core.common` / `discuss.core.common` (bus
  subscriptions), `discuss.rtc` (WebRTC engine), `mail.suggestion` (@mentions),
  `mail.composer`, `mail.attachment_upload`, `mail.sound_effects`, `im_status`, etc. Full
  list below.
- **Entry components:** `DiscussClientAction` (the `mail.action_discuss` client action) →
  `Discuss` app; `Chatter` (form/portal); `ChatWindow`/`ChatHub` (floating chats);
  `MessagingMenu` (systray).

### JS OWL services (registered in `registry.category("services")`)

| Service | File | Purpose |
|---------|------|---------|
| `mail.store` | `core/common/store_service.js` | The reactive Store singleton (the ORM) |
| `mail.core.common` | `core/common/mail_core_common_service.js` | Core bus subscriptions (`mail.record/insert`, message/attachment/settings) |
| `mail.core.web` | `core/web/mail_core_web_service.js` | Backend-web extensions (init messaging, activity) |
| `mail.suggestion` | `core/common/suggestion_service.js` | Composer @mention / #channel / :emoji suggestions |
| `mail.composer` | `core/common/composer_service.js` | Composer send / draft helpers |
| `mail.attachment_upload` | `core/common/attachment_upload_service.js` | File-upload lifecycle |
| `mail.sound_effects` | `core/common/sound_effects_service.js` | Named sound-effect playback |
| `mail.out_of_focus` | `core/common/out_of_focus_service.js` | Tab-blur notification sound/title |
| `mail.popout` | `core/common/mail_popout_service.js` | Pop-out window management |
| `mail.fullscreen` | `core/common/mail_fullscreen.js` | Fullscreen toggle |
| `mail.chat_hub` | `core/common/chat_hub.js` | Owns the ChatHub state |
| `im_status` | `core/common/im_status_service.js` | Presence (im_status) tracking |
| `discuss.core.common` | `discuss/core/common/discuss_core_common_service.js` | Channel bus subscriptions (new_message, member, delete) |
| `discuss.core.web` | `discuss/core/web/discuss_core_web_service.js` | Backend Discuss integration |
| `discuss.core.public.web` | `discuss/core/public_web/discuss_core_public_web_service.js` | Shared Discuss logic (sidebar, categories) |
| `discuss.voice_message` | `discuss/voice_message/common/voice_message_service.js` | Voice-message recording/playback |
| `discuss.rtc` | `discuss/call/common/rtc_service.js` | WebRTC call engine (sessions, tracks, SFU/P2P) |
| `discuss.p2p` | `discuss/call/common/discuss_p2p_service.js` | Peer-to-peer connection layer |
| `discuss.call_invitations` | `discuss/call/common/call_invitations.js` | Incoming call-invitation handling |
| `discuss.ptt_extension` | `discuss/call/common/ptt_extension_service.js` | Push-to-talk browser-extension hook |
| `discuss.pip_service` | `discuss/call/common/pip_service.js` | Picture-in-picture for calls |
| `bus.connection_alert` | `discuss/core/public_web/bus_connection_alert.js` | UI alert on bus disconnection |

### Main components & mounting

| Component | File | Notes |
|-----------|------|-------|
| `DiscussClientAction` | `core/public_web/discuss_client_action.js` | Registered `actions` → `"mail.action_discuss"`; hosts `Discuss` |
| `Discuss` | `core/public_web/discuss.js` | The Discuss UI (sidebar + thread) |
| `MessagingMenu` | `core/public_web/messaging_menu.js` | The systray messaging menu; registers itself into `registry.category("systray")` as `"mail.messaging_menu"` (sequence 25) in that same file |
| `Chatter` | `chatter/web_portal/chatter.js` | Form-view + portal chatter; hosts `Thread` + `Composer` |
| `ChatWindow` / `ChatHub` | `core/common/chat_window.js` / `chat_hub.js` | Floating chat windows + their container |

**Public-page boot** (`discuss/core/public/boot.js`): `whenReady()` → register
`DiscussClientAction` in `main_components` → `makeEnv()` + `startServices(env)` →
`env.services["mail.store"].insert(odoo.discuss_data)` → `mount(MainComponentsContainer,
document.body, …)`. The public page rebuilds the platform standalone (see `mail.assets_public`
in `ASSET_LAYERS.md`).

## Deployment layers

The same feature ships different code per context. Every `static/src/` leaf directory carries
a layer suffix (`common` / `web` / `public_web` / `web_portal` / `public`) that decides its
bundle. This is the module's most distinctive architectural trait — see `ASSET_LAYERS.md`.
The cardinal rule: **`common/` must not import from a higher layer** (it also runs on the
public page, where `web/` is absent).

## File counts

| Category | Count |
|----------|------:|
| Python models (`models/`, incl. `discuss/`) | 76 (+ `__init__`) |
| Python controllers | 21 files · **65** routes |
| Python wizards | 10 |
| Python tests | 58 `test_*.py` |
| JavaScript (`static/src/`) | 392 |
| JS model classes (`extends Record`) | 38 |
| JS OWL services | 22 |
| JS tests (`static/tests/`, `*.test.js`) | 127 |
| SCSS | 132 |
| XML (views + data + demo + OWL templates) | ~380 (41 views + 15 data + 4 demo + 164 static OWL) |
| i18n (.po/.pot) | 64 |
