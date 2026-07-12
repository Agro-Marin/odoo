// @ts-check
/** @odoo-module native */

/** @module @web/legacy/js/public/lazyloader - Lazy script loader that defers event handling until all JS bundles are loaded */

import {
    BUTTON_HANDLER_SELECTOR,
    makeAsyncHandler,
    makeButtonHandler,
} from "@web/legacy/js/public/minimal_dom";

// Track when all JS files have been lazy loaded. Will allow to unblock the
// related DOM sections when the whole JS have been loaded and executed.
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
    await _allScriptsLoaded;
    // Loaded scripts were able to add a delay to wait for before re-triggering
    // events: we wait for it here. Use allSettled, not all: if ANY readiness
    // delay rejects (e.g. a frontend service failed to start), Promise.all
    // would reject and the retrigger below would never run — the user's first
    // (blocked, preventDefault'd) click would be swallowed forever. Log the
    // rejection instead and still replay the event.
    const readinessResults = await Promise.allSettled(retriggeringWaitingProms);
    for (const result of readinessResults) {
        if (result.status === "rejected") {
            console.error("Page readiness delay rejected:", result.reason);
        }
    }

    // At the end of the current execution queue, retrigger the event. The
    // event is reconstructed — necessary in some cases (e.g. submit
    // buttons), probably because the original event was defaultPrevented.
    setTimeout(() => {
        // Extra safety check: the element might have been removed from the DOM
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

    // TODO should probably find the wrapwrap another way but in future versions
    // the element will be gone anyway.
    const mainEl = document.getElementById("wrapwrap") || document.body;
    const loadingEffectButtonEls = [
        ...mainEl.querySelectorAll(BUTTON_HANDLER_SELECTOR),
    ]
        // We target all buttons but...
        .filter((el) => {
            // ... allow disabling the effect via that class. Buttons without
            // it that get handlers from non-lazy code will show a stuck
            // loading effect until lazy JS loads — a known compromise (added
            // as a stable fix), mitigated by caching on later page visits.
            return (
                !el.classList.contains("o_no_wait_lazy_js") &&
                // ... also exclude links with an href other than "#" — even
                // if a handler prevents their default, following the link is
                // still likely relevant.
                !(
                    el.nodeName === "A" &&
                    el.getAttribute("href") &&
                    el.getAttribute("href") !== "#"
                )
            );
        });
    // Note: this is a limitation/a "risk" to only block and retrigger those
    // specific event types.
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
                    ? makeButtonHandler(
                          waitForLazyAndRetrigger,
                          true,
                          true,
                          true,
                      )
                    : makeAsyncHandler(
                          waitForLazyAndRetrigger,
                          true,
                          true,
                          true,
                      );
            registerLoadingEffectHandler(
                buttonEl,
                eventType,
                loadingEffectHandler,
            );
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
}

// Start waiting for lazy loading as soon as the DOM is available
if (document.readyState !== "loading") {
    waitLazy();
} else {
    document.addEventListener("DOMContentLoaded", function () {
        waitLazy();
    });
}

// As soon as the document is fully loaded, start loading the whole remaining JS
if (document.readyState === "complete") {
    setTimeout(_loadScripts, 0);
} else {
    window.addEventListener("load", function () {
        setTimeout(_loadScripts, 0);
    });
}

// Maximum time to wait for a single lazy script to settle ("load" or
// "error") before unblocking the page anyway. A hung request (stalled
// connection, unresponsive server) fires neither event, so without this
// watchdog @see stopWaitingLazy would never run and every button/form
// blocked by @see waitLazy would stay unusable forever. 60s is far beyond
// any sane bundle load time and matches the module loader's
// one-reload-per-minute self-heal guard window.
const SCRIPT_LOAD_TIMEOUT_DELAY = 60000;
/** @type {number | undefined} */
let scriptLoadWatchdogTimer;

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
    clearTimeout(scriptLoadWatchdogTimer);
    if (index >= scripts.length) {
        onAllScriptsDone();
        return;
    }
    const script = scripts[index];
    const loadNext = () => _loadScripts(scripts, index + 1, onAllScriptsDone);
    // Hard timeout fallback: a script that never settles must not keep the
    // page blocked. The chain listeners stay in place: if the script settles
    // after all, loading simply resumes in the background (resolving an
    // already-resolved promise is a no-op).
    scriptLoadWatchdogTimer = setTimeout(() => {
        console.error(
            `Lazy script did not settle within ${SCRIPT_LOAD_TIMEOUT_DELAY}ms,` +
                ` unblocking the page anyway: ${script.src}`,
        );
        onAllScriptsDone();
    }, SCRIPT_LOAD_TIMEOUT_DELAY);
    script.addEventListener("load", loadNext, { once: true });
    script.addEventListener(
        "error",
        () => {
            console.error(`Failed to load lazy script: ${script.src}`);
            loadNext();
        },
        { once: true },
    );
    script.setAttribute("defer", "defer"); // See LAZY_LOAD_DEFER
    script.src = script.dataset.src;
    script.removeAttribute("data-src");
}

export default {
    loadScripts: _loadScripts,
    allScriptsLoaded: _allScriptsLoaded,
    registerPageReadinessDelay: retriggeringWaitingProms.push.bind(
        retriggeringWaitingProms,
    ),
};
