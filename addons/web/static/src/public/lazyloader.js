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
 * @param {HTMLElement} el
 * @param {string} type
 * @param {EventListener} handler
 */
function registerLoadingEffectHandler(el, type, handler) {
    el.addEventListener(type, handler, { capture: true });
    loadingEffectHandlers.push({ el, type, handler });
}

let waitingLazy = false;

/**
 * Adds a loading effect on clicked buttons (unless opted out via a specific
 * class); once the whole JS has loaded, the events are retriggered.
 *
 * Form submits are prevented but not retriggered (would duplicate a submit
 * button's click retrigger) — submitting a form should usually simulate a
 * click on its submit button anyway.
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
    const loadingEffectButtonEls = [
        ...mainEl.querySelectorAll(BUTTON_HANDLER_SELECTOR),
    ].filter(
        (el) =>
            !el.classList.contains("o_no_wait_lazy_js") &&
            !(
                el.nodeName === "A" &&
                el.getAttribute("href") &&
                el.getAttribute("href") !== "#"
            ),
    );
    const loadingEffectEventTypes = [
        "mouseover",
        "mouseenter",
        "mousedown",
        "mouseup",
        "click",
        "mouseout",
        "mouseleave",
    ];
    for (const buttonEl of loadingEffectButtonEls) {
        for (const eventType of loadingEffectEventTypes) {
            const loadingEffectHandler =
                eventType === "click"
                    ? makeButtonHandler(waitForLazyAndRetrigger, true, true, true)
                    : makeAsyncHandler(waitForLazyAndRetrigger, true, true, true);
            registerLoadingEffectHandler(buttonEl, eventType, loadingEffectHandler);
        }
    }

    for (const formEl of /** @type {NodeListOf<HTMLFormElement>} */ (
        document.querySelectorAll("form:not(.o_no_wait_lazy_js)")
    )) {
        registerLoadingEffectHandler(formEl, "submit", (ev) => {
            ev.preventDefault();
            ev.stopImmediatePropagation();
        });
    }
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
    // one record per (button, event type): keeping them would pin every button
    // of the page in memory for as long as the document lives
    loadingEffectHandlers.length = 0;
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
        script.src = script.dataset.src ?? "";
        script.removeAttribute("data-src");
    };
    loadFrom(index);
}

export default {
    loadScripts: _loadScripts,
    allScriptsLoaded: _allScriptsLoaded,
    registerPageReadinessDelay: retriggeringWaitingProms.push.bind(
        retriggeringWaitingProms,
    ),
};
