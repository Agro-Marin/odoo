// @ts-check
/** @odoo-module native */

/** @module @web/public/lazyloader - Lazy script loader that defers event handling until all JS bundles are loaded */

import {
    BUTTON_HANDLER_SELECTOR,
    makeAsyncHandler,
    makeButtonHandler,
} from "@web/public/minimal_dom";

let allScriptsLoadedResolve = null;
const _allScriptsLoaded = new Promise((resolve) => {
    allScriptsLoadedResolve = resolve;
}).then(stopWaitingLazy);

const retriggeringWaitingProms = [];
/**
 * Event handler that replays the incoming event once the lazy JS has
 * loaded. Blocking the incoming event is left to the caller (a potential
 * wrapper, @see waitLazy).
 *
 * @param {Event} ev
 * @returns {Promise<void>}
 */
async function waitForLazyAndRetrigger(ev) {
    const targetEl = /** @type {HTMLElement} */ (ev.target);
    try {
        await _allScriptsLoaded;
    } catch (error) {
        // this runs as a bare DOM listener, so the promise carrying the failure
        // is dropped by the caller and by `makeAsyncHandler`, which had to
        // observe it to release its lock: report it here or nowhere
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

const loadingEffectHandlers = [];
/**
 * Adds the given event listener and saves it for later removal.
 *
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
 * A control the lazy wait is allowed to freeze. An anchor that actually
 * navigates somewhere is left alone: swallowing its click would strand the
 * visitor on the page.
 *
 * @param {Element} el
 * @returns {boolean}
 */
function isLazyWaitTarget(el) {
    const href = el.nodeName === "A" ? el.getAttribute("href") : null;
    return !el.classList.contains("o_no_wait_lazy_js") && !(href && href !== "#");
}

/**
 * The controls the freeze applies to, chosen once when it starts.
 *
 * Delegation could just as well decide per event and would then also cover the
 * controls that appear during the wait — but that is a wider freeze than the
 * one this module has always applied, and widening it is a separate decision
 * from making it cheaper. The set keeps the two apart: same controls as a
 * per-control binding, a handful of listeners instead of seven per control.
 *
 * @type {WeakSet<Element>}
 */
let frozenControls = new WeakSet();

/**
 * The wrapped handler of a (control, event type) pair, built on first use.
 *
 * One per pair and not one per event: the wrappers hold a lock that lets only
 * the first event through, and the events are replayed once the lazy JS has
 * loaded. Sharing a wrapper across controls would let a hover over one button
 * swallow, unreplayed, the click on the next one.
 *
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

/**
 * Adds a loading effect on clicked buttons (unless opted out via a specific
 * class); once the whole JS has loaded, the events are retriggered.
 *
 * Form submits are prevented but not retriggered (would duplicate a submit
 * button's click retrigger) — submitting a form should usually simulate a
 * click on its submit button anyway.
 *
 * Delegated, rather than bound to each control: binding left seven capture
 * listeners and seven closures on every control on the page — thousands of
 * them on a large one. The capture phase runs on an ancestor even for
 * `mouseenter` / `mouseleave`, which do not bubble (measured), and stopping
 * there suppresses the control's own listeners too, which is what the freeze
 * is for.
 *
 * @see stopWaitingLazy
 */
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

    // on the document, because a form may well sit outside the main element
    // (a header login box does), which is what the per-form query covered
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
/**
 * Undo what @see waitLazy did.
 */
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
    // the per-control wrappers close over their controls; fresh collections
    // drop every one of them at once
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
 * Sequentially loads all scripts with a `data-src` attribute, then resolves
 * the allScriptsLoaded promise.
 *
 * A script that fails to load (network error, or a stale content-addressed
 * /web/assets/ URL answering 404 after the attachment GC swept it) logs an
 * error and lets the chain proceed: a page with degraded lazy JS stays
 * interactive, whereas stopping the chain would leave it permanently blocked
 * by @see waitLazy. No observability beacon is sent from here: the module
 * loader shim's capture-phase "error" listener already reports failing
 * /web/assets/ scripts (beacon + one-shot reload self-heal).
 *
 * The watchdog unblocks the page without abandoning the chain — a script that
 * settles late still runs — so completion is reported at most once instead of
 * again when the chain reaches its end.
 *
 * @param {NodeListOf<HTMLScriptElement> | HTMLScriptElement[]} [scripts]
 * @param {number} [index]
 * @param {() => void} [onAllScriptsDone] chain-completion callback; resolves
 *        the allScriptsLoaded promise by default (parameter exists for
 *        testability, production code never passes it)
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
    // per chain, not per module: the watchdog times out the script this chain
    // is waiting on, and a second chain sharing the variable cancelled it
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
            // `script.src = ""` resolves against the document, so an entry with
            // an empty data-src had the browser fetch the page's own HTML and
            // try to run it as a script — a guaranteed parse error, and a whole
            // extra document over the wire. There is nothing to load here.
            script.removeAttribute("data-src");
            loadNext();
            return;
        }
        // only while the page is still waiting: the watchdog exists to unblock
        // it, so once it has been unblocked the remaining scripts finish on
        // their own time. Re-arming it kept a timer alive per script and logged
        // a timeout for each one that was merely slow, long after the message
        // could mean anything.
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
        script.setAttribute("defer", "defer");
        script.src = script.dataset.src;
        script.removeAttribute("data-src");
    };
    loadFrom(index);
}

/**
 * Holds back the replay of the events swallowed during the wait until `prom`
 * settles, so that a retriggered click meets a page that is ready for it.
 *
 * A named function rather than a bound `Array.prototype.push`: that exposed
 * push's whole signature — several promises at once, and an array length as
 * the return value — as the service's contract.
 *
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

// exported for tests only: both run once, off DOMContentLoaded, so there is no
// other way to exercise the freeze
export { stopWaitingLazy, waitLazy };
