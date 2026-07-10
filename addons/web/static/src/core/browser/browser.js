// @ts-check
/** @odoo-module native */

/** @module @web/core/browser/browser - Patchable browser API facade (localStorage, fetch, setTimeout, etc.) for testability */

/** @type {Storage} */
let sessionStorage;
/** @type {Storage} */
let localStorage;
try {
    sessionStorage = window.sessionStorage;
    localStorage = window.localStorage;
    // Safari crashes in Private Browsing
    localStorage.setItem("__localStorage__", "true");
    localStorage.removeItem("__localStorage__");
} catch {
    localStorage = makeRAMLocalStorage();
    sessionStorage = makeRAMLocalStorage();
}

const browserImpl = {
    addEventListener: window.addEventListener.bind(window),
    dispatchEvent: window.dispatchEvent.bind(window),
    AnalyserNode: window.AnalyserNode,
    Audio: window.Audio,
    AudioBufferSourceNode: window.AudioBufferSourceNode,
    AudioContext: window.AudioContext,
    AudioWorkletNode: window.AudioWorkletNode,
    BeforeInstallPromptEvent: /** @type {any} */ (
        window
    ).BeforeInstallPromptEvent?.bind(window),
    GainNode: window.GainNode,
    MediaStreamAudioSourceNode: window.MediaStreamAudioSourceNode,
    removeEventListener: window.removeEventListener.bind(window),
    setTimeout: window.setTimeout.bind(window),
    clearTimeout: window.clearTimeout.bind(window),
    setInterval: window.setInterval.bind(window),
    clearInterval: window.clearInterval.bind(window),
    performance: window.performance,
    // NB: a constructor — must NOT be ``.bind()``-ed (that would break ``new``).
    PerformanceObserver: window.PerformanceObserver,
    requestAnimationFrame: window.requestAnimationFrame.bind(window),
    cancelAnimationFrame: window.cancelAnimationFrame.bind(window),
    console: window.console,
    history: window.history,
    matchMedia: window.matchMedia.bind(window),
    navigator,
    Notification: window.Notification,
    open: window.open.bind(window),
    SharedWorker: window.SharedWorker,
    Worker: window.Worker,
    XMLHttpRequest: window.XMLHttpRequest,
    localStorage,
    sessionStorage,
    fetch: window.fetch.bind(window),
    ontouchstart: window.ontouchstart,
    BroadcastChannel: window.BroadcastChannel,
    visualViewport: window.visualViewport,
};

/**
 * Mutable facade over ``window.location``. The real object has several
 * non-configurable properties, making it unpatchable in tests under modern
 * Chromium ("TypeError: Cannot redefine property: reload"). This forwards to
 * the real location while letting ``patchWithCleanup(browser.location, {...})``
 * override facade-owned properties without touching the real one.
 */
const locationFacade = {
    get href() {
        return window.location.href;
    },
    set href(value) {
        window.location.href = value;
    },
    get origin() {
        return window.location.origin;
    },
    get host() {
        return window.location.host;
    },
    get hostname() {
        return window.location.hostname;
    },
    get pathname() {
        return window.location.pathname;
    },
    get port() {
        return window.location.port;
    },
    get protocol() {
        return window.location.protocol;
    },
    get search() {
        return window.location.search;
    },
    set search(value) {
        window.location.search = value;
    },
    get hash() {
        return window.location.hash;
    },
    set hash(value) {
        window.location.hash = value;
    },
    // The legacy ``reload(true)`` force-reload signature is dead surface
    // (Firefox dropped it in 2019; Chrome never standardised it). No args.
    reload() {
        return window.location.reload();
    },
    assign(/** @type {string | URL} */ url) {
        return window.location.assign(url);
    },
    replace(/** @type {string | URL} */ url) {
        return window.location.replace(url);
    },
    toString() {
        return window.location.toString();
    },
};

Object.defineProperty(browserImpl, "location", {
    // Delegates to the real ``window.location`` so assigning a string still
    // triggers navigation, matching ``window.location = "..."`` semantics.
    set(val) {
        window.location = val;
    },
    get() {
        return locationFacade;
    },
    configurable: true,
});

Object.defineProperty(browserImpl, "innerHeight", {
    get: () => window.innerHeight,
    configurable: true,
});
Object.defineProperty(browserImpl, "innerWidth", {
    get: () => window.innerWidth,
    configurable: true,
});

/**
 * The runtime ``browser`` export: ``browserImpl`` plus the accessors installed
 * via ``Object.defineProperty`` (``location``, ``innerHeight``, ``innerWidth``),
 * which type inference can't see — the cast re-attaches them for type-checking
 * without changing the runtime object.
 */
export const browser =
    /** @type {typeof browserImpl & { location: typeof locationFacade, innerHeight: number, innerWidth: number }} */ (
        browserImpl
    );

// memory localStorage

/**
 * @returns {typeof window["localStorage"]}
 */
export function makeRAMLocalStorage() {
    /** @type {{[key: string]: string}} */
    let store = Object.create(null);
    // Real Storage fires ``storage`` events only in OTHER same-origin documents,
    // never the writing window. This single-window in-memory fallback (used when
    // window.localStorage is unavailable, e.g. Safari Private Browsing) must
    // dispatch none at all — doing so on set/remove previously gave same-window
    // listeners phantom cross-tab notifications the native API never produces.
    return {
        setItem(key, value) {
            store[key] = String(value);
        },
        getItem(key) {
            return store[key] ?? null;
        },
        clear() {
            store = Object.create(null);
        },
        removeItem(key) {
            delete store[key];
        },
        get length() {
            return Object.keys(store).length;
        },
        key(index) {
            return Object.keys(store)[index] ?? null;
        },
    };
}
