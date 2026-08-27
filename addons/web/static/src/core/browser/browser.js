// @ts-check
/** @odoo-module native */

/** @type {Storage} */
let sessionStorage;
/** @type {Storage} */
let localStorage;
try {
    sessionStorage = window.sessionStorage;
    localStorage = window.localStorage;
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
    BarcodeDetector: /** @type {any} */ (window).BarcodeDetector,
    BeforeInstallPromptEvent: /** @type {any} */ (window).BeforeInstallPromptEvent,
    GainNode: window.GainNode,
    MediaStream: window.MediaStream,
    MediaStreamAudioSourceNode: window.MediaStreamAudioSourceNode,
    RTCPeerConnection: window.RTCPeerConnection,
    removeEventListener: window.removeEventListener.bind(window),
    setTimeout: window.setTimeout.bind(window),
    clearTimeout: window.clearTimeout.bind(window),
    setInterval: window.setInterval.bind(window),
    clearInterval: window.clearInterval.bind(window),
    performance: window.performance,
    crypto: window.crypto,
    indexedDB: window.indexedDB,
    PerformanceObserver: window.PerformanceObserver,
    requestAnimationFrame: window.requestAnimationFrame.bind(window),
    cancelAnimationFrame: window.cancelAnimationFrame.bind(window),
    console: window.console,
    history: window.history,
    matchMedia: window.matchMedia.bind(window),
    navigator,
    Notification: window.Notification,
    open: window.open.bind(window),
    scrollTo: window.scrollTo.bind(window),
    SharedWorker: window.SharedWorker,
    Worker: window.Worker,
    XMLHttpRequest: window.XMLHttpRequest,
    localStorage,
    sessionStorage,
    fetch: window.fetch.bind(window),
    BroadcastChannel: window.BroadcastChannel,
    visualViewport: window.visualViewport,
};

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
    set(val) {
        window.location = val;
    },
    get() {
        return locationFacade;
    },
    configurable: true,
});

Object.defineProperty(browserImpl, "ontouchstart", {
    get: () => window.ontouchstart,
    configurable: true,
});
Object.defineProperty(browserImpl, "innerHeight", {
    get: () => window.innerHeight,
    configurable: true,
});
Object.defineProperty(browserImpl, "scrollX", {
    get: () => window.scrollX,
    configurable: true,
});
Object.defineProperty(browserImpl, "scrollY", {
    get: () => window.scrollY,
    configurable: true,
});
Object.defineProperty(browserImpl, "innerWidth", {
    get: () => window.innerWidth,
    configurable: true,
});

export const browser =
    /** @type {typeof browserImpl & { location: typeof locationFacade, innerHeight: number, innerWidth: number, scrollX: number, scrollY: number, ontouchstart: ((this: Window, ev: TouchEvent) => any) | null | undefined, }} */ (
        browserImpl
    );

/**
 * @returns {typeof window["localStorage"]}
 */
function makeRAMLocalStorage() {
    /** @type {{[key: string]: string}} */
    let store = Object.create(null);
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
