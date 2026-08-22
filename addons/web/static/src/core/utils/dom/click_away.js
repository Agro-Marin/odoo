// @ts-check
/** @odoo-module native */

import { onMounted, onWillDestroy } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";

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

    function armIframe(/** @type {HTMLIFrameElement} */ iframeEl) {
        const win = iframeEl.contentWindow;
        if (!win || armedWindows.has(win)) {
            return;
        }
        const handler = () => {
            const contentEl = getContentEl?.();
            let checkEl = iframeEl.parentElement;
            while (checkEl) {
                if (checkEl === contentEl) {
                    return;
                }
                checkEl = checkEl.parentElement;
            }
            callback(iframeEl);
        };
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
            /** @type {FocusEvent} */ (ev).relatedTarget || document.activeElement;
        if (/** @type {Element} */ (target)?.tagName === "IFRAME") {
            scanIframes();
            return callback(/** @type {Node} */ (target));
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
        callback(/** @type {Node} */ (ev.composedPath()[0]));
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
