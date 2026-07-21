# Asset Layers — deployment-context bundling

> The `mail` JS is organized into **layers by deployment context**, not by feature. The
> same feature (e.g. a thread, a composer) ships different code depending on *where* it
> runs: the backend webclient, a portal page, or the anonymous public discuss page. This
> doc is the reference for that layering — mail's analogue of web's `ESM_BUNDLING.md`.

> **See also**: `__manifest__.py` (`assets` dict + `esm` dict — the source of truth),
> `DIRECTORY_MAP.md` (which directories belong to which layer), `ARCHITECTURE.md`.

## The five layers

Every leaf directory under `static/src/` carries a **layer suffix** (`.../common/...`,
`.../web/...`, etc.). The suffix decides which bundle(s) the file lands in:

| Layer | Runs in | Shipped by |
|-------|---------|------------|
| `common/` | **everywhere** — backend, portal, and the anonymous public/livechat page | `web.assets_backend` + `mail.assets_public` (+ named sub-bundles) |
| `web/` | backend webclient only | `web.assets_backend` |
| `public_web/` | shared between backend and the public discuss page | `web.assets_backend` + `mail.assets_public` |
| `web_portal/` | portal + backend | `web.assets_backend` (+ standalone `mail.assets_*_web_portal`) |
| `public/` | anonymous public discuss page only | `mail.assets_public` |

**The import rule that makes this work:** `common/` may **not** import from any higher
layer; higher layers import downward only (`web` → `public_web` → `common`). A `common/`
file importing from `web/` would break the public page (where `web/` is absent). See
CONVENTIONS.md.

Directories on disk carrying these suffixes: `core/{common,public_web,web_portal,web}`,
`chatter/{web,web_portal}`, `discuss/call/{common,public,public_web,web}`,
`discuss/core/{common,public,public_web,web}`,
`discuss/{gif_picker,message_pin,typing,voice_message}/common`, `discuss/web`,
`utils/common`, `views/web`, `webclient/web`.

## Backend bundle composition (`web.assets_backend`)

Layers load in a strict order via two glob families:

```python
# explicit core layers first…
"mail/static/src/core/common/**/*",
"mail/static/src/core/public_web/**/*",
"mail/static/src/core/web_portal/**/*",
"mail/static/src/core/web/**/*",
# …then wildcard layer globs across every feature
"mail/static/src/**/common/**/*",
"mail/static/src/**/public_web/**/*",
"mail/static/src/**/web_portal/**/*",
"mail/static/src/**/web/**/*",
```

### The discuss remove-then-re-add

Those `**/common/**` etc. wildcards also match `discuss/**`, so discuss is **stripped and
re-added** as one deterministic block:

```python
("remove", "mail/static/src/discuss/**/*"),
"mail/static/src/discuss/core/common/**/*",
"mail/static/src/discuss/core/public_web/**/*",
"mail/static/src/discuss/core/web/**/*",
"mail/static/src/discuss/**/common/**/*",   # + public_web, web
```

**Why (per the manifest comment):** the historical core → discuss import inversion has been
fixed, so **JS imports no longer require this ordering**. It is kept for two remaining
reasons:
1. **SCSS cascade** — discuss styles must come after core styles so they override them.
2. **Side-effect module order** — patches and registry additions that have no import edge
   between them run in this deterministic block order.

`*.dark.scss` files are `("remove", ...)`'d from the layer bundles and shipped separately in
`web.assets_web_dark`.

## Public-page bundle (`mail.assets_public`)

`mail.assets_public` is a **self-contained** bundle for the anonymous discuss page — it does
not assume the webclient is present, so it re-includes the web platform from scratch:
`web._assets_helpers`, `web._assets_backend_helpers`, bootstrap SCSS, fontawesome7,
`web._assets_core`, `web/static/src/fields/formatters.js`, all of `bus/static/src/**` (minus
`bus_worker_script.js`), and `html_editor._assets_editor`. Then it adds mail's
`common` + `public_web` + `public` layers plus the discuss block (mirroring the
remove-then-re-add pattern, but with `public_web`/`public` instead of `web`/`web_portal`),
and strips `*.dark.scss`.

## Named sub-bundles (the supported extension seam)

Downstream modules (portal, im_livechat, …) embed mail layers by `("include", ...)`-ing
these named bundles **instead of** globbing `mail/static/src/**` paths — this decouples them
from mail's internal file layout. They deliberately keep `*.dark.scss` (the consumer decides
whether to strip them).

| Bundle | Contains | For |
|--------|----------|-----|
| `mail.assets_core_common` | `model/**`, `utils/common/**`, `core/common/**` | Core store/model + common UI, minimal footprint |
| `mail.assets_discuss_core_common` | `discuss/core/common/**` | Discuss channel core |
| `mail.assets_discuss_call_common` | `discuss/call/common/**` | RTC/call core |
| `mail.assets_discuss_typing_common` | `discuss/typing/common/**` | Typing indicator |
| `mail.assets_core_web_portal` | `core/web_portal/**` | Portal core |
| `mail.assets_chatter_web_portal` | `chatter/web_portal/**` | Portal chatter |
| `mail.assets_public` | full standalone public-page bundle (see above) | The anonymous discuss page |
| `mail.assets_message_email` | `web/static/lib/odoo_ui_icons/style.css` | Icon CSS embedded in email HTML |
| `mail.assets_odoo_sfu` | `static/lib/odoo_sfu/odoo_sfu.js` | Lazy-loaded SFU client |
| `mail.assets_lamejs` | `static/lib/lame/lame.js` | Lazy-loaded MP3 encoder |
| `mail.assets_discuss_public_test_tours` | hoot-dom + web_tour + 6 public-page tour files (5 `tours/discuss_channel_*` + `discuss_sidebar_in_public_page_tour.js`) | Public-page browser tests |

## ESM wiring (`esm` manifest key)

Four bundles are esbuild-compiled as native ESM:

```python
"esm": {
    "bundles": [
        "mail.assets_lamejs", "mail.assets_odoo_sfu",
        "mail.assets_public", "mail.assets_discuss_public_test_tours",
    ],
    "dynamic_children": {
        "web.assets_web": ["mail.assets_lamejs", "mail.assets_odoo_sfu"],
    },
    "secondary_import_map_includes": {
        "mail.assets_public": ["mail.assets_discuss_public_test_tours"],
    },
}
```

- **`dynamic_children`** — `mail.assets_lamejs` and `mail.assets_odoo_sfu` are registered in
  `web.assets_web`'s import map for **lazy** `import()` (the MP3 encoder and SFU client are
  only fetched when a user actually records a voice message or joins a call).
- **`secondary_import_map_includes`** — `mail.assets_discuss_public_test_tours` loads as a
  separate `<script type="module">` **after** `mail.assets_public`, piggybacking on the
  parent's import map so its native imports (hoot-dom, `@web/core/templates`) resolve. The
  manifest comment notes: without ESM compilation this bundle's legacy-loader bridge would
  resolve native modules to `undefined` at pre-boot, breaking every discuss public-page
  browser test.

## Vendored libraries (`static/lib/`)

| Library | Version | For | Loaded via |
|---------|---------|-----|-----------|
| `idb-keyval/idb-keyval.js` | 3.2.0 | IndexedDB key/value store (client store persistence) | `web.assets_backend` (eager) |
| `lame/lame.js` | 1.2.1 (lamejs) | MP3 encoder for voice-message recording | `mail.assets_lamejs` (lazy) |
| `odoo_sfu/odoo_sfu.js` | 1.3.3 | Odoo SFU (Selective Forwarding Unit) WebRTC client | `mail.assets_odoo_sfu` (lazy) |
| `selfie_segmentation/selfie_segmentation.js` | 0.1.1632777926 (MediaPipe build id) | MediaPipe selfie segmentation — call background blur | `web.assets_backend` + `mail.assets_public` (eager) |

> `selfie_segmentation.js` is eager in `web.assets_backend` — do **not** `loadJS` it after
> page load (it is already in the initial bundle; re-evaluating is a hazard). This is the
> exact case called out in web's `CONVENTIONS.md` gotcha on `loadJS`.

## Frontend & other bundles

- `web.assets_frontend` — only `mail/static/src/utils/common/format.js` (mail's date/format
  helpers reused by non-backend frontend pages).
- `web.assets_web_dark` — `mail/static/src/**/*.dark.scss`.
- `web.assets_unit_tests` — `mail/static/tests/**/*` (minus `tours/**`) plus
  `mail/static/src/service_worker_utils.js` (the worker is served as raw text, not bundled,
  but its helpers are exposed to HOOT for unit testing).
- `web.assets_tests` — `mail/static/tests/tours/**/*` (browser tours).
