// @ts-check
/** @odoo-module native */

/** @module @web/core/browser/router - URL routing: parse, serialize, and push browser history state */

import { EventBus } from "@odoo/owl";
import { isDisplayStandalone } from "@web/core/browser/feature_detection";
import { RouterEvent } from "@web/core/events";
import { slidingWindow } from "@web/core/utils/collections/arrays";
import { deepEqual, omit, pick } from "@web/core/utils/collections/objects";
import { isNumeric } from "@web/core/utils/format/strings";
import { compareUrls, objectToUrlEncodedString } from "@web/core/utils/urls";

import { browser } from "./browser.js";

export const PATH_KEYS = ["resId", "action", "active_id", "model"];

export const routerBus = new EventBus();

function isScopedApp() {
    return browser.location.href.includes("/scoped_app") && isDisplayStandalone();
}

/**
 * Casts the given string to a number if possible.
 *
 * @param {string} value
 * @returns {string|number}
 */
function cast(value) {
    if (!value) {
        return value;
    }
    const n = Number(value);
    return Number.isFinite(n) && String(n) === value ? n : value;
}

/**
 * @typedef {{ [key: string]: string }} Query
 * @typedef {{ [key: string]: any }} Route
 */

/**
 * Decodes a URI component, returning the raw string when it contains
 * malformed percent-encoding (e.g. "%E0%A4%A" or a lone "%"). This module
 * parses the location at evaluation time — an unguarded URIError here
 * would blank the whole app on boot.
 *
 * @param {string} s
 * @returns {string}
 */
function tryDecode(s) {
    try {
        return decodeURIComponent(s);
    } catch {
        return s;
    }
}

function parseString(/** @type {string} */ str) {
    if (!str) {
        return Object.create(null);
    }
    const parts = str.split("&");
    const result = Object.create(null);
    for (const part of parts) {
        const eqIdx = part.indexOf("=");
        const rawKey = eqIdx === -1 ? part : part.slice(0, eqIdx);
        const key = tryDecode(rawKey);
        if (key === "__proto__" || key === "constructor" || key === "prototype") {
            continue;
        }
        const value = eqIdx === -1 ? "" : part.slice(eqIdx + 1);
        const decoded = tryDecode(value || "");
        result[key] = cast(decoded);
    }
    return result;
}
/**
 * @param {object} values An object with the values of the new state
 * @param {boolean} replace whether the values should replace the state or be
 *  layered on top of the current state
 * @returns {object} the next state of the router
 */
function computeNextState(values, replace) {
    const nextState = replace ? pick(state, ..._lockedKeys) : { ...state };
    Object.assign(nextState, values);
    if (nextState.actionStack?.length) {
        Object.assign(nextState.actionStack.at(-1), pick(nextState, ...PATH_KEYS));
    }
    return sanitizeSearch(nextState);
}

function sanitize(
    /** @type {Record<string, any>} */ obj,
    /** @type {any} */ valueToRemove,
) {
    return Object.fromEntries(
        Object.entries(obj)
            .filter(([, v]) => v !== valueToRemove)
            .map(([k, v]) => [k, cast(v)]),
    );
}

function sanitizeSearch(/** @type {Record<string, any>} */ search) {
    return sanitize(search, undefined);
}

function sanitizeHash(/** @type {Record<string, any>} */ hash) {
    return sanitize(hash, "");
}

/**
 * @param {string} hash
 * @returns {any}
 */
export function parseHash(hash) {
    return hash && hash !== "#" ? parseString(hash.slice(1)) : {};
}

/**
 * @param {string} search
 * @returns {any}
 */
export function parseSearchQuery(search) {
    return search ? parseString(search.slice(1)) : {};
}

function pathFromActionState(/** @type {Route} */ state) {
    const path = [];
    const { action, model, active_id, resId } = state;
    if (active_id && typeof active_id === "number") {
        path.push(active_id);
    }
    if (action) {
        if (typeof action === "number" || action.includes(".")) {
            path.push(`action-${action}`);
        } else {
            path.push(action);
        }
    } else if (model) {
        if (model.includes(".")) {
            path.push(model);
        } else {
            path.push(`m-${model}`);
        }
    }
    if (resId && (typeof resId === "number" || resId === "new")) {
        path.push(resId);
    }
    return path.join("/");
}

export function startUrl() {
    return isScopedApp() ? "scoped_app" : "odoo";
}

/**
 * @param {{ [key: string]: any }} state
 * @returns
 */
function stateToUrl(state) {
    let path = "";
    const keysToOmit = new Set(_hiddenKeysFromUrl);
    const actionStack = (state.actionStack || [state]).map(
        (/** @type {Record<string, any>} */ a) => ({ ...a }),
    );
    if (actionStack.at(-1)?.action !== "menu") {
        for (const [prevAct, currentAct] of slidingWindow(actionStack, 2).reverse()) {
            const {
                action: prevAction,
                resId: prevResId,
                active_id: prevActiveId,
            } = prevAct;
            const { action: currentAction, active_id: currentActiveId } = currentAct;
            if (currentActiveId === prevResId) {
                delete currentAct.active_id;
            }
            if (
                prevAction === currentAction &&
                !prevResId &&
                currentActiveId === prevActiveId
            ) {
                delete currentAct.action;
                delete currentAct.active_id;
            }
        }
        const pathSegments = actionStack.map(pathFromActionState).filter(Boolean);
        if (pathSegments.length) {
            path = `/${pathSegments.join("/")}`;
        }
    }
    if (state.active_id && typeof state.active_id !== "number") {
        keysToOmit.delete("active_id");
    }
    if (state.resId && typeof state.resId !== "number" && state.resId !== "new") {
        keysToOmit.delete("resId");
    }
    const search = objectToUrlEncodedString(omit(state, ...keysToOmit));
    const start_url = startUrl();
    return `/${start_url}${path}${search ? `?${search}` : ""}`;
}

function urlToState(/** @type {URL} */ urlObj) {
    const { pathname, hash, search } = urlObj;
    const state = parseSearchQuery(search);

    if (pathname === "/web") {
        const sanitizedHash = sanitizeHash(parseHash(hash));
        if (sanitizedHash.id) {
            sanitizedHash.resId = sanitizedHash.id;
            delete sanitizedHash.id;
            delete sanitizedHash.view_type;
        } else if (sanitizedHash.view_type === "form") {
            sanitizedHash.resId = "new";
            delete sanitizedHash.view_type;
        }
        Object.assign(state, sanitizedHash);
        const url = browser.location.origin + router.stateToUrl(state);
        urlObj.href = url;
    }

    const [prefix, ...splitPath] = urlObj.pathname.split("/").filter(Boolean);

    if (["odoo", "scoped_app"].includes(prefix)) {
        const actionParts = [...splitPath.entries()].filter(
            ([_, part]) => !isNumeric(part) && part !== "new",
        );
        const actions = [];
        for (const [i, part] of actionParts) {
            /** @type {Record<string, any>} */
            const action = {};
            const [left, right] = [splitPath[i - 1], splitPath[i + 1]];
            if (isNumeric(left)) {
                action.active_id = Number.parseInt(left, 10);
            }

            if (right === "new") {
                action.resId = "new";
            } else if (isNumeric(right)) {
                action.resId = Number.parseInt(right, 10);
            }

            if (part.startsWith("action-")) {
                const actionId = part.slice(7);
                action.action = isNumeric(actionId)
                    ? Number.parseInt(actionId, 10)
                    : actionId;
            } else if (part.startsWith("m-")) {
                action.model = part.slice(2);
            } else if (part.includes(".")) {
                action.model = part;
            } else {
                action.action = part;
            }

            if (action.resId && action.action) {
                actions.push(omit(action, "resId"));
            }
            if (action.action || action.resId || i === splitPath.length - 1) {
                actions.push(action);
            }
        }
        const activeAction = actions.at(-1);
        if (activeAction) {
            Object.assign(state, activeAction);
            state.actionStack = actions;
        }
        if (prefix === "scoped_app" && !isDisplayStandalone()) {
            const url = browser.location.origin + router.stateToUrl(state);
            urlObj.href = url;
        }
    }
    return state;
}

/** @type {Record<string, any>} */
let state;
/** @type {any} */
let pushTimeout;
/** @type {{ replace: boolean, reload: boolean, state: Record<string, any>, mode: "push" | "replace", title?: string }} */
let pushArgs;

/**
 * Fresh aggregation bucket for debounced push/replace. `mode` starts at the
 * weakest intent ("replace"); a "push" call upgrades it so batched calls never
 * silently downgrade an intended new history entry.
 * @returns {{ replace: boolean, reload: boolean, state: Record<string, any>, mode: "push" | "replace" }}
 */
function makePushArgs() {
    return { replace: false, reload: false, state: {}, mode: "replace" };
}
/** @type {Set<string>} */
let _lockedKeys;
let _hiddenKeysFromUrl = new Set();

export function startRouter() {
    const url = new URL(/** @type {any} */ (browser.location));
    state = router.urlToState(url);
    if (browser.location.pathname === "/web") {
        browser.history.replaceState(browser.history.state, "", url.href);
    }
    pushTimeout = null;
    pushArgs = makePushArgs();
    _lockedKeys = new Set(["debug", "lang"]);
    _hiddenKeysFromUrl = new Set([...PATH_KEYS, "actionStack"]);
}

/**
 * When the user navigates history using the back/forward button, the browser
 * dispatches a popstate event with the state that was in the history for the
 * corresponding history entry. We adopt that state directly so the webclient
 * can reuse it without a full page reload.
 */
browser.addEventListener("popstate", (ev) => {
    browser.clearTimeout(pushTimeout);
    pushArgs = makePushArgs();
    if (!ev.state) {
        browser.history.replaceState({ nextState: state }, "", browser.location.href);
        return;
    }
    const previousState = state;
    state =
        ev.state?.nextState ||
        router.urlToState(new URL(/** @type {any} */ (browser.location)));
    // Landing back on the state we are already on is not a navigation: it pops
    // a *synthetic* entry someone stacked on top of ours (BottomSheet pushes one
    // so the Back gesture closes the sheet instead of leaving the page, then
    // pops it again when the sheet closes by any other means). Reloading there
    // is never merely redundant — `loadState` re-enters `doAction`, whose
    // KeepLast supersedes whatever action is still loading, so a tap that both
    // closes a sheet and opens an action cancels the action and re-renders the
    // controller already on screen. `skipRouteChange` cannot express this: it
    // is read off the entry we land *on*, not the synthetic one we left.
    const routeChanged = !deepEqual(previousState, state);
    if (!ev.state?.skipRouteChange && !router.skipLoad && routeChanged) {
        routerBus.trigger(RouterEvent.ROUTE_CHANGE);
    }
    router.skipLoad = false;
});

/**
 * Safari (iOS and macOS) can restore the page from the `bfcache` on back/forward
 * navigation (especially when returning from an external website). Odoo isn't
 * compatible with this cache, so when it's used to restore a page, reload it to
 * ensure everything is rendered correctly.
 */
browser.addEventListener("pageshow", (ev) => {
    if (ev.persisted) {
        router.cancelPushes();
        routerBus.trigger(RouterEvent.ROUTE_CHANGE);
    }
});

/**
 * When clicking internal links, do a loadState instead of a full page reload.
 * This also allows the mobile app to not open an in-app browser for them.
 */
browser.addEventListener("click", (ev) => {
    if (ev.button !== 0 || ev.ctrlKey || ev.metaKey || ev.shiftKey || ev.altKey) {
        return;
    }
    const target = /** @type {Element} */ (ev.target);
    if (ev.defaultPrevented || target.closest("[contenteditable]")) {
        return;
    }
    const a = target.closest("a");
    if (!a) {
        return;
    }
    const href = a.getAttribute("href");
    if (href && !href.startsWith("#")) {
        let url;
        try {
            url = new URL(a.href);
        } catch {
            return;
        }
        const prefix = `/${startUrl()}`;
        const onAppPath =
            browser.location.pathname === prefix ||
            browser.location.pathname.startsWith(`${prefix}/`);
        const targetIsApp =
            ["/web", prefix].includes(url.pathname) ||
            url.pathname.startsWith(`${prefix}/`);
        if (
            browser.location.host === url.host &&
            onAppPath &&
            targetIsApp &&
            a.target !== "_blank" &&
            !a.hasAttribute("download")
        ) {
            ev.preventDefault();
            router.cancelPushes();
            state = router.urlToState(url);
            if (url.pathname.startsWith(prefix) && url.hash) {
                browser.history.pushState({ nextState: state }, "", url.href);
            }
            browser.setTimeout(() => routerBus.trigger(RouterEvent.ROUTE_CHANGE), 0);
        }
    }
});

/**
 * @param {string} mode
 */
function makeDebouncedPush(mode) {
    function doPush() {
        const nextState = computeNextState(pushArgs.state, pushArgs.replace);
        const url = browser.location.origin + router.stateToUrl(nextState);
        if (!compareUrls(url + browser.location.hash, browser.location.href)) {
            if (pushArgs.mode === "push") {
                const originalTitle = document.title;
                document.title = /** @type {string} */ (pushArgs.title);
                browser.history.pushState({ nextState }, "", url);
                document.title = originalTitle;
            } else {
                browser.history.replaceState({ nextState }, "", url);
            }
        } else {
            browser.history.replaceState({ nextState }, "", browser.location.href);
        }
        state = nextState;
        if (pushArgs.reload) {
            browser.location.reload();
        }
    }
    /**
     * @param {Record<string, any>} state
     * @param {{ replace?: boolean, reload?: boolean, sync?: boolean }} [options]
     */
    return function pushOrReplaceState(state, options = {}) {
        pushArgs.replace ||= /** @type {boolean} */ (options.replace);
        pushArgs.reload ||= /** @type {boolean} */ (options.reload);
        if (mode === "push") {
            pushArgs.mode = "push";
        }
        pushArgs.title = document.title;
        Object.assign(pushArgs.state, state);
        browser.clearTimeout(pushTimeout);
        const push = () => {
            doPush();
            pushTimeout = null;
            pushArgs = makePushArgs();
        };
        if (options.sync) {
            push();
        } else {
            pushTimeout = browser.setTimeout(() => {
                push();
            });
        }
    };
}

export const router = {
    get current() {
        return state;
    },
    stateToUrl,
    urlToState,
    pushState: makeDebouncedPush("push"),
    replaceState: makeDebouncedPush("replace"),
    cancelPushes: () => {
        browser.clearTimeout(pushTimeout);
        pushArgs = makePushArgs();
    },
    addLockedKey: (/** @type {string} */ key) => _lockedKeys.add(key),
    hideKeyFromUrl: (/** @type {string} */ key) => _hiddenKeysFromUrl.add(key),
    skipLoad: false,
};

startRouter();
