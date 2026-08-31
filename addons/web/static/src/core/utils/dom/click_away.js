// @ts-check
/** @odoo-module native */

import { onMounted, onWillDestroy } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { getActiveElement } from "@web/core/utils/dom/ui";

/**
 * @param {EventTarget} target
 * @param {string} eventName
 * @param {(ev: Event) => any} handler
 * @param {AddEventListenerOptions} [eventParams]
 */
function useEarlyExternalListener(target, eventName, handler, eventParams) {
    target.addEventListener(eventName, handler, eventParams);
    onWillDestroy(() => target.removeEventListener(eventName, handler, eventParams));
}

/**
 * Whether `node` is part of the widget delimited by `getAnchor` / `getContentEl`.
 *
 * @param {EventTarget | Node | null | undefined} node
 * @param {(() => (Element | null | undefined)) | undefined} getAnchor
 * @param {(() => (Element | null | undefined)) | undefined} getContentEl
 * @returns {boolean}
 */
function isInsideWidget(node, getAnchor, getContentEl) {
    if (!node) {
        return false;
    }
    const target = /** @type {Node} */ (node);
    return Boolean(
        getAnchor?.()?.contains(target) || getContentEl?.()?.contains(target),
    );
}

/**
 * Calls `callback` when the user acts *outside* the hooked widget.
 *
 * The anchor and the content element are what "outside" is measured against: a
 * pointerdown or a focus move landing inside either one is not an away event
 * and never reaches `callback`. Callers therefore do not repeat the containment
 * test — before this was centralised, three of the four callers each spelled it
 * differently and `Pager` omitted it, which made clicking inside its own open
 * input collapse the input.
 *
 * A navigation is always an away event: nothing can be "inside" a page that is
 * being left.
 *
 * @param {(node?: Node) => any} callback
 * @param {Object} [options]
 * @param {() => (Element | null | undefined)} [options.getAnchor]
 * @param {() => (Element | null | undefined)} [options.getContentEl]
 */
export function useClickAway(callback, { getAnchor, getContentEl } = {}) {
    /** @type {(() => void)[]} */
    const iframeDisposers = [];
    /** @type {WeakSet<Window>} */
    const armedWindows = new WeakSet();

    /** @param {Node} [node] */
    const callbackIfAway = (node) => {
        if (!isInsideWidget(node, getAnchor, getContentEl)) {
            callback(node);
        }
    };

    function armIframe(/** @type {HTMLIFrameElement} */ iframeEl) {
        const win = iframeEl.contentWindow;
        if (!win || armedWindows.has(win)) {
            return;
        }
        const handler = () => callbackIfAway(iframeEl);
        try {
            win.addEventListener("pointerdown", handler, { capture: true });
            armedWindows.add(win);
            iframeDisposers.push(() =>
                win.removeEventListener("pointerdown", handler, { capture: true }),
            );
        } catch (e) {
            if (e.name !== "SecurityError") {
                throw e;
            }
        }
    }

    /** @returns {(Document | ShadowRoot)[]} */
    function iframeRoots() {
        const anchorRoot = getAnchor?.()?.getRootNode?.();
        return anchorRoot && anchorRoot !== document
            ? [document, /** @type {ShadowRoot} */ (anchorRoot)]
            : [document];
    }

    function scanIframes() {
        for (const root of iframeRoots()) {
            for (const iframeEl of root.querySelectorAll("iframe")) {
                armIframe(/** @type {HTMLIFrameElement} */ (iframeEl));
            }
        }
    }

    function blurHandler(/** @type {Event} */ ev) {
        const target =
            /** @type {FocusEvent} */ (ev).relatedTarget ||
            getActiveElement(/** @type {Node} */ (ev.target));
        if (/** @type {Element} */ (target)?.tagName === "IFRAME") {
            scanIframes();
            return callbackIfAway(/** @type {Node} */ (target));
        }
    }

    let lastHref = browser.location.href;
    function navigationHandler() {
        if (browser.location.href === lastHref) {
            return;
        }
        lastHref = browser.location.href;
        callback(document.documentElement);
    }

    function pointerDownHandler(/** @type {Event} */ ev) {
        callbackIfAway(/** @type {Node} */ (ev.composedPath()[0]));
    }

    useEarlyExternalListener(window, "pointerdown", pointerDownHandler, {
        capture: true,
    });
    useEarlyExternalListener(window, "blur", blurHandler, { capture: true });
    useEarlyExternalListener(window, "popstate", navigationHandler, {
        capture: true,
    });
    scanIframes();
    onMounted(() => scanIframes());
    onWillDestroy(() => {
        for (const dispose of iframeDisposers) {
            dispose();
        }
    });
}
