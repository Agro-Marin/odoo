// @ts-check
/** @odoo-module native */

import {
    BUTTON_HANDLER_SELECTOR,
    makeAsyncHandler,
    makeButtonHandler,
} from "@web/public/minimal_dom";

/** @type {(value?: any) => void} */
let allScriptsLoadedResolve = () => {};
const _allScriptsLoaded = new Promise((resolve) => {
    allScriptsLoadedResolve = resolve;
}).then(stopWaitingLazy);

/** @type {Promise<any>[]} */
const retriggeringWaitingProms = [];
/**
 * @param {Event} ev
 * @returns {Promise<void>}
 */
async function waitForLazyAndRetrigger(ev) {
    const targetEl = /** @type {HTMLElement} */ (ev.target);
    try {
        await _allScriptsLoaded;
    } catch (error) {
        console.error("Lazy script loading failed:", error);
    }
    const readinessResults = await Promise.allSettled(retriggeringWaitingProms);
    for (const result of readinessResults) {
        if (result.status === "rejected") {
            console.error("Page readiness delay rejected:", result.reason);
        }
    }

    setTimeout(() => {
        if (targetEl.isConnected) {
            const EventCtor =
                /** @type {new (type: string, init?: EventInit) => Event} */ (
                    ev.constructor
                );
            targetEl.dispatchEvent(new EventCtor(ev.type, ev));
        }
    }, 0);
}

/** @type {Array<{ el: HTMLElement | Document, type: string, handler: EventListener }>} */
const loadingEffectHandlers = [];
/**
 * @param {HTMLElement | Document} el
 * @param {string} type
 * @param {EventListener} handler
 */
function registerLoadingEffectHandler(el, type, handler) {
    el.addEventListener(type, handler, { capture: true });
    loadingEffectHandlers.push({ el, type, handler });
}

let waitingLazy = false;

const LOADING_EFFECT_EVENT_TYPES = [
    "mouseover",
    "mouseenter",
    "mousedown",
    "mouseup",
    "click",
    "mouseout",
    "mouseleave",
];

/**
 * @param {Element} el
 * @returns {boolean}
 */
function isLazyWaitTarget(el) {
    const href = el.nodeName === "A" ? el.getAttribute("href") : null;
    return !el.classList.contains("o_no_wait_lazy_js") && !(href && href !== "#");
}

/**
 * @type {WeakSet<Element>}
 */
let frozenControls = new WeakSet();

/**
 * @type {WeakMap<Element, Map<string, (ev: Event) => any>>}
 */
let delegatedHandlers = new WeakMap();

/**
 * @param {Element} el
 * @param {string} type
 * @returns {(ev: Event) => any}
 */
function loadingEffectHandlerFor(el, type) {
    let byType = delegatedHandlers.get(el);
    if (!byType) {
        byType = new Map();
        delegatedHandlers.set(el, byType);
    }
    let handler = byType.get(type);
    if (!handler) {
        handler =
            type === "click"
                ? makeButtonHandler(waitForLazyAndRetrigger, true, true, true)
                : makeAsyncHandler(waitForLazyAndRetrigger, true, true, true);
        byType.set(type, handler);
    }
    return handler;
}

function waitLazy() {
    if (waitingLazy) {
        return;
    }
    waitingLazy = true;

    document.body.classList.add("o_lazy_js_waiting");

    const mainEl = document.getElementById("wrapwrap") || document.body;
    frozenControls = new WeakSet(
        [...mainEl.querySelectorAll(BUTTON_HANDLER_SELECTOR)].filter(isLazyWaitTarget),
    );
    for (const eventType of LOADING_EFFECT_EVENT_TYPES) {
        registerLoadingEffectHandler(mainEl, eventType, (ev) => {
            const el = /** @type {Element | null} */ (ev.target)?.closest?.(
                BUTTON_HANDLER_SELECTOR,
            );
            if (!el || !frozenControls.has(el)) {
                return;
            }
            loadingEffectHandlerFor(el, ev.type).call(el, ev);
        });
    }

    const frozenForms = new WeakSet(
        document.querySelectorAll("form:not(.o_no_wait_lazy_js)"),
    );
    registerLoadingEffectHandler(document, "submit", (ev) => {
        const formEl = /** @type {Element | null} */ (ev.target)?.closest?.("form");
        if (!formEl || !frozenForms.has(formEl)) {
            return;
        }
        ev.preventDefault();
        ev.stopImmediatePropagation();
    });
}
function stopWaitingLazy() {
    if (!waitingLazy) {
        return;
    }
    waitingLazy = false;

    document.body.classList.remove("o_lazy_js_waiting");

    for (const { el, type, handler } of loadingEffectHandlers) {
        el.removeEventListener(type, handler, { capture: true });
    }
    loadingEffectHandlers.length = 0;
    delegatedHandlers = new WeakMap();
    frozenControls = new WeakSet();
}

if (document.readyState !== "loading") {
    waitLazy();
} else {
    document.addEventListener("DOMContentLoaded", function () {
        waitLazy();
    });
}

if (document.readyState === "complete") {
    setTimeout(_loadScripts, 0);
} else {
    window.addEventListener("load", function () {
        setTimeout(_loadScripts, 0);
    });
}

const SCRIPT_LOAD_TIMEOUT_DELAY = 60000;

/**
 * @param {NodeListOf<HTMLScriptElement> | HTMLScriptElement[]} [scripts]
 * @param {number} [index]
 * @param {() => void} [onAllScriptsDone]
 * @returns {void}
 */
function _loadScripts(scripts, index, onAllScriptsDone) {
    if (scripts === undefined) {
        scripts = document.querySelectorAll("script[data-src]");
    }
    if (index === undefined) {
        index = 0;
    }
    if (onAllScriptsDone === undefined) {
        onAllScriptsDone = allScriptsLoadedResolve;
    }
    /** @type {number | undefined} */
    let watchdogTimer;
    let hasReportedDone = false;
    const reportDone = () => {
        if (!hasReportedDone) {
            hasReportedDone = true;
            onAllScriptsDone();
        }
    };
    /** @param {number} i */
    const loadFrom = (i) => {
        clearTimeout(watchdogTimer);
        if (i >= scripts.length) {
            reportDone();
            return;
        }
        const script = scripts[i];
        const loadNext = () => loadFrom(i + 1);
        if (!script.dataset.src) {
            script.removeAttribute("data-src");
            loadNext();
            return;
        }
        if (!hasReportedDone) {
            watchdogTimer = setTimeout(() => {
                console.error(
                    `Lazy script did not settle within ${SCRIPT_LOAD_TIMEOUT_DELAY}ms,` +
                        ` unblocking the page anyway: ${script.src}`,
                );
                reportDone();
            }, SCRIPT_LOAD_TIMEOUT_DELAY);
        }
        script.addEventListener("load", loadNext, { once: true });
        script.addEventListener(
            "error",
            () => {
                console.error(`Failed to load lazy script: ${script.src}`);
                loadNext();
            },
            { once: true },
        );
        script.src = script.dataset.src;
        script.removeAttribute("data-src");
    };
    loadFrom(index);
}

/**
 * @param {Promise<any>} prom
 * @returns {void}
 */
function registerPageReadinessDelay(prom) {
    retriggeringWaitingProms.push(prom);
}

export default {
    loadScripts: _loadScripts,
    allScriptsLoaded: _allScriptsLoaded,
    registerPageReadinessDelay,
};

export { stopWaitingLazy, waitLazy };
