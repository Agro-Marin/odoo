// @ts-check
/** @odoo-module native */

/** @module @web/core/events - Typed event constants for bus communication */

/**
 * Global application events dispatched on `env.bus`.
 *
 * Usage:
 *   import { AppEvent } from "@web/core/events";
 *   env.bus.trigger(AppEvent.WEB_CLIENT_READY);
 *   env.bus.addEventListener(AppEvent.MENUS_APP_CHANGED, handler);
 *
 * Existing string literals continue to work — adopt these constants in new
 * code for discoverability and refactoring safety.
 */
export const AppEvent = Object.freeze({
    // ── Lifecycle ───────────────────────────────────────────────────────────
    /** All services loaded and env is ready. Fired once at startup. */
    SERVICES_LOADED: "SERVICES-LOADED",
    /** WebClient component is mounted and ready. Fired once. */
    WEB_CLIENT_READY: "WEB_CLIENT_READY",

    // ── Action Manager ──────────────────────────────────────────────────────
    /** Action manager updated its current controller. */
    ACTION_MANAGER_UPDATE: "ACTION_MANAGER:UPDATE",
    /** Action manager finished UI rendering after an update. */
    ACTION_MANAGER_UI_UPDATED: "ACTION_MANAGER:UI-UPDATED",
    /** Request to load the default app (home menu). */
    WEBCLIENT_LOAD_DEFAULT_APP: "WEBCLIENT:LOAD_DEFAULT_APP",
    /** Request all controllers to save/discard unsaved changes. */
    CLEAR_UNCOMMITTED_CHANGES: "CLEAR-UNCOMMITTED-CHANGES",

    // ── Menu ────────────────────────────────────────────────────────────────
    /** Current app changed in the menu service. */
    MENUS_APP_CHANGED: "MENUS:APP-CHANGED",
    /** Home-menu visibility toggled. Emitted by the enterprise
     *  `home_menu_service`; consumed by the web burger menu and the
     *  enterprise navbar / studio navbar. Lives in `AppEvent` (not in an
     *  enterprise-only enum) so the community burger menu can subscribe
     *  without taking a hard dep on enterprise. */
    HOME_MENU_TOGGLED: "HOME-MENU:TOGGLED",

    // ── UI ──────────────────────────────────────────────────────────────────
    /** Block the UI (show loading overlay). */
    BLOCK: "BLOCK",
    /** Unblock the UI. */
    UNBLOCK: "UNBLOCK",
    /** Active element (dialog/main) changed. */
    ACTIVE_ELEMENT_CHANGED: "active-element-changed",
    /** Window resized. */
    RESIZE: "resize",
});

/**
 * Events dispatched on the RPC bus (`rpcBus`).
 *
 * Usage:
 *   import { RpcEvent } from "@web/core/events";
 *   import { rpcBus } from "@web/core/network/rpc";
 *   rpcBus.addEventListener(RpcEvent.REQUEST, handler);
 */
export const RpcEvent = Object.freeze({
    /** An RPC request was sent. */
    REQUEST: "RPC:REQUEST",
    /** An RPC response was received. */
    RESPONSE: "RPC:RESPONSE",
    /** Clear all client-side caches (ORM, name_get, etc.). */
    CLEAR_CACHES: "CLEAR-CACHES",
});

/**
 * Events dispatched on the router bus (`routerBus`).
 *
 * Usage:
 *   import { RouterEvent } from "@web/core/events";
 *   import { routerBus } from "@web/core/browser/router";
 *   routerBus.addEventListener(RouterEvent.ROUTE_CHANGE, handler);
 */
export const RouterEvent = Object.freeze({
    /** URL hash/search changed. */
    ROUTE_CHANGE: "ROUTE_CHANGE",
});

/**
 * Events dispatched on a model's local bus (``model.bus``). Scoped to one
 * model lifecycle (not ``env.bus``); field widgets and view controllers rely
 * on this contract.
 *
 * Usage:
 *   import { ModelEvent } from "@web/core/events";
 *   useBus(this.props.record.model.bus, ModelEvent.WILL_SAVE_URGENTLY, () => ...);
 *
 * Addons with their own model-like bus (e.g. web_studio's
 * ``reportEditorModel.bus``) can reuse these string constants directly.
 */
export const ModelEvent = Object.freeze({
    /** Model finished loading/notifying — consumers should re-render. */
    UPDATE: "update",
    /** Tab-close save path is starting; field widgets must flush pending
     *  edits synchronously (sendBeacon can't await microtasks). */
    WILL_SAVE_URGENTLY: "WILL_SAVE_URGENTLY",
    /** A save / discard / dirty-check is about to read the record's
     *  ``data``; field widgets with debounced/local pending edits must
     *  commit them before the read. Detail is ``{ proms: Promise[] }``;
     *  listeners push a promise into ``proms`` and the emitter awaits
     *  ``Promise.all(proms)`` before proceeding. */
    NEED_LOCAL_CHANGES: "NEED_LOCAL_CHANGES",
    /** Per-field "I have unsaved local edits" signal. Detail is a boolean.
     *  Consumed by the form status indicator and list keyboard navigator
     *  to know that a debounced input is in-flight even though the record
     *  hasn't been committed yet. Emitted by input-bearing field widgets
     *  (Char/Text/Datetime/Domain/Ace) on focus/blur/typing transitions. */
    FIELD_IS_DIRTY: "FIELD_IS_DIRTY",
    /** A property-field cell wants to switch to edit mode. Detail is empty;
     *  the properties_field listener computes the appropriate UX (typically
     *  prompts the user to save first if the parent record is dirty). */
    PROPERTY_FIELD_EDIT: "PROPERTY_FIELD:EDIT",
    /** Calendar model asks the renderer to scroll the visible viewport to
     *  the current hour line. Detail is a boolean (smooth scroll flag).
     *  Calendar-view scoped — not used by other model types. */
    SCROLL_TO_CURRENT_HOUR: "SCROLL_TO_CURRENT_HOUR",
});

/**
 * Events dispatched on the search model's bus (``env.searchModel``), scoped
 * to one view's search-model lifecycle (not ``env.bus``). Contract between
 * the search layer (control panel, search bar, search panel) and the views.
 *
 * Usage:
 *   import { SearchModelEvent } from "@web/core/events";
 *   useBus(this.env.searchModel, SearchModelEvent.UPDATE, () => ...);
 */
export const SearchModelEvent = Object.freeze({
    /** Search state changed (facets, filters, search panel values) —
     *  consumers should re-render / reload. */
    UPDATE: "update",
    /** Ask the view to take focus back (e.g. pressing ArrowDown from
     *  the search bar, or its "focus view" command). */
    FOCUS_VIEW: "focus-view",
    /** Ask the search bar input to take focus (e.g. pressing ArrowUp
     *  from the first record of a list/kanban view). */
    FOCUS_SEARCH: "focus-search",
    /** Ask the view to export its records directly (export-all button
     *  in the control panel's cog menu). */
    DIRECT_EXPORT_DATA: "direct-export-data",
});

/**
 * Events dispatched on the `user` service's public `userBus`
 * (`import { userBus } from "@web/services/user"`).
 *
 * Consumed by the switch-company menu, the user-menu, and the reload-
 * company service. Scoped to identity/authorization state changes.
 *
 * Usage:
 *   import { UserEvent } from "@web/core/events";
 *   import { userBus } from "@web/services/user";
 *   useBus(userBus, UserEvent.ACTIVE_COMPANIES_CHANGED, () => ...);
 */
export const UserEvent = Object.freeze({
    /** The set of active companies (multi-company selector) changed. */
    ACTIVE_COMPANIES_CHANGED: "ACTIVE_COMPANIES_CHANGED",
});

/**
 * Events dispatched on the `file_upload` service's public bus
 * (`useService("file_upload").bus`).
 *
 * Consumed cross-addon (mail, hr_fleet, product, enterprise/documents).
 * String values are the public contract — addons that have not yet
 * migrated to the typed constants keep working unchanged.
 *
 * Usage:
 *   import { FileUploadEvent } from "@web/core/events";
 *   useBus(fileUpload.bus, FileUploadEvent.LOADED, (ev) => ...);
 */
export const FileUploadEvent = Object.freeze({
    /** A new upload has been registered (XHR not started yet). */
    ADDED: "FILE_UPLOAD_ADDED",
    /** Upload completed successfully (HTTP 2xx). */
    LOADED: "FILE_UPLOAD_LOADED",
    /** Upload failed (HTTP non-2xx, network error, or aborted). */
    ERROR: "FILE_UPLOAD_ERROR",
});

/**
 * Events dispatched on a command-palette `bus` instance.
 *
 * Scoped to one palette lifetime (the palette owns a bus passed to its
 * content components); consumed only inside `services/commands/`. Typed
 * for refactor safety even though the consumer set is small.
 *
 * Usage:
 *   import { CommandPaletteEvent } from "@web/core/events";
 *   bus.addEventListener(CommandPaletteEvent.SET_CONFIG, handler);
 */
export const CommandPaletteEvent = Object.freeze({
    /** Palette config changed (placeholder, debounce, footer, etc.). */
    SET_CONFIG: "SET-CONFIG",
});
