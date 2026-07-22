# Public-Site Interaction Framework

> The website analog of web's `STATE_MANAGEMENT.md`. Where the backend webclient
> is an OWL SPA, the public site is **server-rendered HTML animated by
> Interactions** — small DOM-bound controllers. This doc is the reference for
> writing, registering, and edit-enabling them.

## What an Interaction is

An **Interaction** (base class `Interaction`, from `@web/public/interaction`) is
a controller bound to DOM elements matched by a static CSS `selector`. When the
public page loads, the framework instantiates one Interaction per matching
element and runs its lifecycle. It is the modern replacement for the legacy
`publicWidget.Widget` (which still runs alongside — see "Legacy layer" below).

Key distinction from OWL: **Interactions do not own or render the DOM** — the
server already rendered it. They attach behavior (event handlers, dynamic
attributes) *over* existing elements. The `dynamicContent` syntax borrows OWL's
`t-on-`/`t-att-` spelling for familiarity, but the semantics differ.

## Minimal example

```js
/** @odoo-module native */
import { registry } from "@web/core/registry";
import { Interaction } from "@web/public/interaction";

export class ScrollButton extends Interaction {
    static selector = ".o_scroll_button";           // one instance per match
    dynamicContent = {
        _root: { "t-on-click": this.onClick },       // bind click on the matched el
    };

    setup() { /* services ready, this.el available */ }
    onClick(ev) { /* handler; updateContent() runs automatically after */ }
}

registry.category("public.interactions").add("website.scroll_button", ScrollButton);
```

Real files: `interactions/scroll_button.js`, `interactions/anchor_slide.js`,
`interactions/_example.js` (annotated skeleton).

## Lifecycle

The framework (the **Colibri** engine, `@web/public/colibri`) drives each
instance through:

| Hook | When | Notes |
|------|------|-------|
| `constructor(el, env, metadata)` | instantiation | **Do not override** — use `setup()`. Sets `this.el`, `this.env`, `this.services`. |
| `setup()` | synchronously after construction | Initialize state. `this.el` and services are available. |
| `async willStart()` | after setup | For async prep (RPC, dynamic imports). The framework **awaits** this before applying dynamic content. |
| `start()` | after `willStart` resolves | The "mounted" equivalent — event handlers are now attached. |
| `destroy()` | on teardown | Clean up side effects. Interactions are **not** destroyed in the normal browsing flow, but *are* when switching to edit mode — clean up after yourself. |

Readiness flags: `this.isReady`, `this.isDestroyed`.

## `dynamicContent`

An object mapping a selector (or a special root) → a set of directives applied
and re-applied by the framework:

```js
dynamicContent = {
    ".some-child":  { "t-on-click": (ev) => this.onClick(ev) },
    ".other-child": {
        "t-att-class": () => ({ "is-active": this.state.active }),
        "t-att-style": () => ({ color: this.color }),
        "t-att-disabled": () => this.locked,   // true → attr name; false/null/undefined → removed
        "t-out": () => this.label,
    },
    _root: { "t-component": () => [SomeOwlComponent, { prop: "value" }] },
};
```

- **Directives:** `t-on-<event>`, `t-att-<attr>`, `t-out`, `t-component` (mount an OWL component into the public page).
- **Special selector roots** (from `dynamicSelectors`): `_root` (`this.el`), `_body`, `_document`, `_window`. A dynamic selector returning a falsy value is silently ignored.
- **Attribute value semantics:** for class/style, a falsy property removes it; for other attributes, `false`/`undefined`/`null` remove it, `""`/`0` apply as-is (`required=""`), boolean `true` applies the attribute name (`required="required"`). `Interaction.INITIAL_VALUE` resets a `t-att-*`/`t-out` to its pre-start value.
- `updateContent()` re-applies all directives; it runs automatically after every event handler and most helpers, so you rarely call it directly. Return `SKIP_IMPLICIT_UPDATE` from a handler to skip it.

## Helpers (on the base class)

| Helper | Purpose |
|--------|---------|
| `waitFor(promise)` | Resolve only if not destroyed; calls `updateContent()` after. |
| `addListener(target, event, fn, options)` | DOM listener auto-removed on destroy. |
| `debounced(fn, delay, options)` / `throttled(fn)` | Lifecycle-aware debounce/throttle (auto-cancelled on destroy). |
| `registerCleanup(fn)` | Register an arbitrary teardown callback. |

Selector refinement: `static selectorHas` / `static selectorNotHas` emulate
`:has()` / `:not(:has())` (used instead of the CSS pseudo-classes for consistent
browser support).

## Registration & startup

Runtime interactions register into the **`public.interactions`** registry:

```js
registry.category("public.interactions").add("website.<name>", MyInteraction);
```

The **`public.interactions` service** (`@web/public/interaction_service`) owns
startup. On page load it calls `startInteractions(el = documentElement)`, which:
1. Reads every class in `registry.category("public.interactions")`.
2. Validates that `selector` is a **static** class property (not instance) and `dynamicContent` is an **instance** property (not static). A violation is **not** fatal: the service pushes a rejected promise and `continue`s (logged via `[public.interactions] interaction failed:`), so one misdeclared interaction no longer aborts the whole scan (it used to throw synchronously, killing every later interaction page-wide).
3. For each element matching a class's `selector`, creates a `Colibri` that instantiates the Interaction and runs its lifecycle.

`startInteractions(el)` / `stopInteractions(el)` can re-scan a subtree — e.g.
after an async Google Maps load (`core/website_map_service.js`) inserts new DOM.

> There are ~38 `public.interactions` registrations across `interactions/` and
> `snippets/`: headers (`header_standard`/`fixed`/`top`/`fade_out`), `popup` /
> `shared_popup` / `cookies_bar`, `carousel_slider`, `parallax`, `media_video`,
> `text_highlight`, `anchor_slide`, `scroll_button`, `post_link`,
> `listing_layout`, `search_modal`, `plausible_push`, `ripple_effect`,
> `animation`, plus snippet-specific ones (`s_countdown`, `s_chart`,
> `s_dynamic_snippet`, …).

## Edit-mode: the `.edit.js` mixin pattern

The editor loads the **real public page** inside an iframe, then makes its
interactions editable — instead of a separate editor runtime. This is website's
signature layering trick.

An interaction opts into edit behavior with a sibling `*.edit.js` file that
registers a **mixin** into `public.interactions.edit`:

```js
// interactions/animation.edit.js
import { Animation } from "./animation.js";

const AnimationEdit = (I) => class extends I {
    destroy() { this.el.classList.remove("o_animate_preview"); }   // edit-only cleanup
};

registry.category("public.interactions.edit").add("website.animation", {
    Interaction: Animation,   // the runtime class this augments
    mixin: AnimationEdit,     // (BaseClass) => SubClass
});
```

`core/website_edit_service.js`:
- `buildEditableInteractions(builders)` collects the registered mixins, walks each interaction's prototype chain, and applies the mixins from top-most class down — producing an *editable* subclass named `<Name>__mixin`.
- The service also `patch()`es `Colibri.prototype`, `Interaction.prototype`, and the interaction-service prototype to add edit-mode plumbing (e.g. `withHistory(dynamicContent)`).
- It hooks the runtime via a deliberate `window` property (not an ESM export) because `website_edit_service.js` is stripped from the frontend bundle and only present inside `website.assets_inside_builder_iframe`; an export would be tree-shaken.

There are ~44 `public.interactions.edit` registrations. Public OWL components
(`<owl-component/>`) get the analogous treatment via
`core/component_interaction_edit.js` and the `public_components.edit` registry.

**Bundle mechanics** (see `ARCHITECTURE.md` / manifest): `web.assets_frontend`
**removes** every `*.edit.js`; `website.assets_inside_builder_iframe` re-adds
`**/*.edit.*` + `website_edit_service.js`. So a visitor never ships edit code;
the editor iframe does.

## Legacy layer (still active)

Not everything has migrated to Interactions. Running alongside:

- **`js/content/website_root.js`** — `WebsiteRoot extends PublicRoot` (`@web/legacy/js/public/public_root`). Binds legacy page-level events (language switch, publish button, Google Maps API requests, `ready_to_clean_for_save`, `seo_object_request`). The manifest `replace`s the framework's `public_root_instance.js` with website's `website_root_instance.js`.
- **`js/content/snippets.animation.js`** — adds the edit-mode notion (`disabledInEditableMode`, `edit_events`, `read_events`) to the legacy `publicWidget.Widget` base.
- **`web.assets_frontend_minimal`** — a tiny early-boot bundle (`inject_dom.js`, `auto_hide_menu.js`, `redirect.js`, `adapt_content.js`, `generate_video_iframe.js`) that runs before the main frontend bundle. `auto_hide_menu.js` coordinates with the editor through `window.__odooWebsiteEditHooks`.

When adding public-site behavior, **prefer a new Interaction** over extending
`publicWidget`. Reserve the legacy layer for code that plugs into `PublicRoot`'s
page-level event bus.

## Frontend services (`core/`)

Public-runtime services (registered in `registry.category("services")`), consumed
by interactions:

| Service | File | Purpose |
|---------|------|---------|
| `website_menus` | `core/website_menus_service.js` | Pub/sub callbacks fired when the top menu changes. |
| `website_page` | `core/website_page_service.js` | Current page context (website_id, lang) + parsed `mainObject` from `<html data-main-object>`. |
| `website_cookies` | `core/website_cookies_service.js` | EventBus + iframe-`src` management gated on consent (`data-need-cookies-approval`). Deps: `public.interactions`. |
| `website_map` | `core/website_map_service.js` | Loads the Google Maps API on demand, then re-starts map interactions. Deps: `public.interactions`, `notification`. |
| `website_edit` | `core/website_edit_service.js` | Builds editable interactions (edit-mode bundle only). |

## Decision guide

```
Adding visitor-facing behavior to a rendered page/snippet?
│
├─ Bind events / dynamic attrs to server-rendered DOM?
│  └─ New Interaction: static selector + dynamicContent, register in
│     "public.interactions". Edit-mode differences? add a *.edit.js mixin.
│
├─ Mount an OWL component into the public page?
│  └─ dynamicContent _root: { "t-component": () => [Comp, props] }
│     (edit support via public_components.edit if needed)
│
├─ Page-level event that PublicRoot already brokers (lang, publish, gmap)?
│  └─ Extend the legacy WebsiteRoot / publicWidget layer.
│
└─ Editor-only option UI (sidebar panel for a snippet)?
   └─ That's the BUILDER, not an Interaction — a BaseOptionComponent +
      *_option_plugin.js under builder/plugins/options/ (see ARCHITECTURE.md).
```
