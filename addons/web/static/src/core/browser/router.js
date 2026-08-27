// @ts-check
/** @odoo-module native */

import { EventBus } from "@odoo/owl";
import { isDisplayStandalone } from "@web/core/browser/feature_detection";
import { RouterEvent } from "@web/core/events";
import { slidingWindow } from "@web/core/utils/collections/arrays";
import { deepEqual, omit, pick } from "@web/core/utils/collections/objects";
import { isNumeric } from "@web/core/utils/format/strings";
import { globalSingleton } from "@web/core/utils/global_singleton";
import { compareUrls, objectToUrlEncodedString } from "@web/core/utils/urls";

import { browser } from "./browser.js";

export const PATH_KEYS = ["resId", "action", "active_id", "model"];

/**
 * @typedef {{
 * bus: EventBus,
 * started: boolean,
 * state: Record<string, any>,
 * pushTimeout: ReturnType<typeof browser.setTimeout> | undefined,
 * pushArgs: PushArgs,
 * lockedKeys: Set<string>,
 * hiddenKeysFromUrl: Set<string>,
 * ephemeralStack: (object | null)[],
 * unwindingEphemerals: boolean,
 * }} RouterState
 * @typedef {{
 * replace: boolean,
 * reload: boolean,
 * state: Record<string, any>,
 * mode: "push" | "replace",
 * title?: string,
 * }} PushArgs
 */

/**
 * @type {RouterState}
 */
const _router = globalSingleton(
    "router",
    () =>
        /** @type {RouterState} */ ({
            bus: new EventBus(),
            started: false,
            state: {},
            pushTimeout: undefined,
            pushArgs: { replace: false, reload: false, state: {}, mode: "replace" },
            lockedKeys: new Set(),
            hiddenKeysFromUrl: new Set(),
            ephemeralStack: [],
            unwindingEphemerals: false,
        }),
);

export const routerBus = _router.bus;

function isScopedApp() {
    return browser.location.href.includes("/scoped_app") && isDisplayStandalone();
}

/**
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
 * @param {object} values
 * @param {boolean} replace
 * @returns {object}
 */
function computeNextState(values, replace) {
    const nextState = replace
        ? pick(_router.state, ..._router.lockedKeys)
        : { ..._router.state };
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
 */
function stateToUrl(state) {
    let path = "";
    const keysToOmit = new Set(_router.hiddenKeysFromUrl);
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

/**
 * @returns {PushArgs}
 */
function makePushArgs() {
    return { replace: false, reload: false, state: {}, mode: "replace" };
}

export function startRouter() {
    const url = new URL(/** @type {any} */ (browser.location));
    _router.state = router.urlToState(url);
    if (browser.location.pathname === "/web") {
        browser.history.replaceState(browser.history.state, "", url.href);
    }
    _router.pushTimeout = undefined;
    _router.pushArgs = makePushArgs();
    _router.ephemeralStack = [];
    _router.unwindingEphemerals = false;
    _router.lockedKeys = new Set(["debug", "lang"]);
    _router.hiddenKeysFromUrl = new Set([...PATH_KEYS, "actionStack"]);
}

function unwindReleasedEphemerals() {
    let count = 0;
    while (_router.ephemeralStack.length && _router.ephemeralStack.at(-1) === null) {
        _router.ephemeralStack.pop();
        count++;
    }
    if (count) {
        _router.unwindingEphemerals = true;
        browser.history.go(-count);
    }
}

function onPopState(/** @type {any} */ ev) {
    browser.clearTimeout(_router.pushTimeout);
    _router.pushArgs = makePushArgs();
    if (_router.unwindingEphemerals) {
        _router.unwindingEphemerals = false;
        _router.state = ev.state?.nextState || _router.state;
        return;
    }
    const ephemeralDepth = ev.state?.ephemeralDepth ?? 0;
    if (ephemeralDepth < _router.ephemeralStack.length) {
        const markers = _router.ephemeralStack.splice(ephemeralDepth);
        _router.state = ev.state?.nextState || _router.state;
        routerBus.trigger(RouterEvent.EPHEMERAL_POPPED, { markers });
        return;
    }
    if (!ev.state) {
        browser.history.replaceState(
            { nextState: _router.state },
            "",
            browser.location.href,
        );
        return;
    }
    const previousState = _router.state;
    _router.state =
        ev.state?.nextState ||
        router.urlToState(new URL(/** @type {any} */ (browser.location)));
    const routeChanged = !deepEqual(previousState, _router.state);
    if (!ev.state?.skipRouteChange && routeChanged) {
        routerBus.trigger(RouterEvent.ROUTE_CHANGE);
    }
}

function onPageShow(/** @type {any} */ ev) {
    if (ev.persisted) {
        router.cancelPushes();
        routerBus.trigger(RouterEvent.ROUTE_CHANGE);
    }
}

function onClick(/** @type {any} */ ev) {
    if (ev.button !== 0 || ev.ctrlKey || ev.metaKey || ev.shiftKey || ev.altKey) {
        return;
    }
    // `ev.target` is retargeted at every shadow boundary, so a click on an
    // anchor inside a shadow root arrives as the HOST: `closest("a")` then
    // answers with whatever anchor encloses the host in the light DOM, and the
    // router navigates somewhere the user never clicked. The composed path's
    // first entry is the element actually clicked, and it is what the
    // `[contenteditable]` opt-out has to be measured against too.
    const target = /** @type {Element} */ (ev.composedPath?.()[0] ?? ev.target);
    if (typeof target?.closest !== "function") {
        return;
    }
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
            _router.state = router.urlToState(url);
            if (url.pathname.startsWith(prefix) && url.hash) {
                browser.history.pushState({ nextState: _router.state }, "", url.href);
            }
            browser.setTimeout(() => routerBus.trigger(RouterEvent.ROUTE_CHANGE), 0);
        }
    }
}

/**
 * @param {string} mode
 */
function makeDebouncedPush(mode) {
    function doPush() {
        const pushArgs = _router.pushArgs;
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
        _router.state = nextState;
        if (pushArgs.reload) {
            browser.location.reload();
        }
    }
    /**
     * @param {Record<string, any>} state
     * @param {{ replace?: boolean, reload?: boolean, sync?: boolean }} [options]
     */
    return function pushOrReplaceState(state, options = {}) {
        const pushArgs = _router.pushArgs;
        pushArgs.replace ||= /** @type {boolean} */ (options.replace);
        pushArgs.reload ||= /** @type {boolean} */ (options.reload);
        if (mode === "push") {
            pushArgs.mode = "push";
        }
        pushArgs.title = document.title;
        Object.assign(pushArgs.state, state);
        browser.clearTimeout(_router.pushTimeout);
        const push = () => {
            try {
                doPush();
            } catch (error) {
                if (
                    error.name !== "NS_ERROR_ILLEGAL_VALUE" &&
                    error.name !== "DataCloneError"
                ) {
                    throw error;
                }
                console.error(error);
            } finally {
                _router.pushTimeout = undefined;
                _router.pushArgs = makePushArgs();
            }
        };
        if (options.sync) {
            push();
        } else {
            _router.pushTimeout = browser.setTimeout(() => {
                push();
            });
        }
    };
}

export const router = {
    get current() {
        return _router.state;
    },
    stateToUrl,
    urlToState,
    pushState: makeDebouncedPush("push"),
    replaceState: makeDebouncedPush("replace"),
    cancelPushes: () => {
        browser.clearTimeout(_router.pushTimeout);
        _router.pushArgs = makePushArgs();
    },
    addLockedKey: (/** @type {string} */ key) => _router.lockedKeys.add(key),
    hideKeyFromUrl: (/** @type {string} */ key) => _router.hiddenKeysFromUrl.add(key),

    /**
     * @param {object} marker
     */
    pushEphemeral: (marker) => {
        _router.ephemeralStack.push(marker);
        browser.history.pushState(
            {
                ...browser.history.state,
                ephemeralDepth: _router.ephemeralStack.length,
                skipRouteChange: true,
            },
            "",
            browser.location.href,
        );
    },

    dropEphemerals: () => {
        _router.ephemeralStack.length = 0;
    },

    /**
     * @param {object} marker
     */
    releaseEphemeral: (marker) => {
        const index = _router.ephemeralStack.indexOf(marker);
        if (index === -1) {
            return;
        }
        _router.ephemeralStack[index] = null;
        unwindReleasedEphemerals();
    },

    /** @returns {number} */
    get ephemeralDepth() {
        return _router.ephemeralStack.length;
    },
};

if (!_router.started) {
    _router.started = true;
    browser.addEventListener("popstate", onPopState);
    browser.addEventListener("pageshow", onPageShow);
    browser.addEventListener("click", onClick);
    startRouter();
}
