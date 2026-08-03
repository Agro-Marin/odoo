// @ts-check
/** @odoo-module native */

/** @module @web/core/events */

export const AppEvent = Object.freeze({
    SERVICES_LOADED: "SERVICES-LOADED",
    WEB_CLIENT_READY: "WEB_CLIENT_READY",

    ACTION_MANAGER_UPDATE: "ACTION_MANAGER:UPDATE",
    ACTION_MANAGER_UI_UPDATED: "ACTION_MANAGER:UI-UPDATED",
    // Fires once per `doAction`, when the dispatch is over -- including the
    // outcomes that change nothing on screen, which `UI-UPDATED` cannot report
    // because there is no UI update to report. Anything waiting on an action
    // rather than on its visible effect wants this one.
    ACTION_MANAGER_SETTLED: "ACTION_MANAGER:SETTLED",
    WEBCLIENT_LOAD_DEFAULT_APP: "WEBCLIENT:LOAD_DEFAULT_APP",
    CLEAR_UNCOMMITTED_CHANGES: "CLEAR-UNCOMMITTED-CHANGES",

    MENUS_APP_CHANGED: "MENUS:APP-CHANGED",
    HOME_MENU_TOGGLED: "HOME-MENU:TOGGLED",

    BLOCK: "BLOCK",
    UNBLOCK: "UNBLOCK",
    ACTIVE_ELEMENT_CHANGED: "active-element-changed",
    RESIZE: "resize",
});

export const RpcEvent = Object.freeze({
    REQUEST: "RPC:REQUEST",
    RESPONSE: "RPC:RESPONSE",
    CLEAR_CACHES: "CLEAR-CACHES",
    BACKGROUND_REFRESH_FAILED: "RPC:BACKGROUND-REFRESH-FAILED",
});

export const RouterEvent = Object.freeze({
    ROUTE_CHANGE: "ROUTE_CHANGE",
    EPHEMERAL_POPPED: "EPHEMERAL_POPPED",
});

export const ModelEvent = Object.freeze({
    UPDATE: "update",
    WILL_SAVE_URGENTLY: "WILL_SAVE_URGENTLY",
    NEED_LOCAL_CHANGES: "NEED_LOCAL_CHANGES",
    FIELD_IS_DIRTY: "FIELD_IS_DIRTY",
    PROPERTY_FIELD_EDIT: "PROPERTY_FIELD:EDIT",
    SCROLL_TO_CURRENT_HOUR: "SCROLL_TO_CURRENT_HOUR",
});

export const SearchModelEvent = Object.freeze({
    UPDATE: "update",
    FOCUS_VIEW: "focus-view",
    FOCUS_SEARCH: "focus-search",
    DIRECT_EXPORT_DATA: "direct-export-data",
});

export const UserEvent = Object.freeze({
    ACTIVE_COMPANIES_CHANGED: "ACTIVE_COMPANIES_CHANGED",
});

export const FileUploadEvent = Object.freeze({
    ADDED: "FILE_UPLOAD_ADDED",
    LOADED: "FILE_UPLOAD_LOADED",
    ERROR: "FILE_UPLOAD_ERROR",
});

export const CommandPaletteEvent = Object.freeze({
    SET_CONFIG: "SET-CONFIG",
});
