// @ts-check
/** @odoo-module native */

/** @module @web/core/utils/dom/dvu - Dynamic viewport units with virtual keyboard and visualViewport tracking */

/**
 * Tracks visualViewport (not just window innerWidth/innerHeight) so
 * dimensions reflect virtual-keyboard appearance, pinch-zoom, and mobile
 * browser UI changes — none of which reliably affect innerWidth/innerHeight.
 * Falls back to window dimensions when visualViewport/VirtualKeyboard APIs
 * are unavailable (older browsers, some embedded webviews).
 *
 * @see https://developer.mozilla.org/en-US/docs/Web/API/VirtualKeyboard_API
 */

import { onWillUnmount } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { isVirtualKeyboardSupported } from "@web/core/browser/feature_detection";
import { throttleForAnimation } from "@web/core/utils/timing";

/**
 * Sources are subscribed to on the first listener and released with the last,
 * NOT at module scope.
 *
 * `browser` is a mutable indirection — tests swap `visualViewport`,
 * `navigator` and the `addEventListener` implementation on it. Binding at
 * module-evaluation time captured whichever `browser` happened to be installed
 * when some unrelated module first pulled this one in, so the subscription
 * could outlive the object it was made against and then never fire again. That
 * made behaviour depend on import order, and left three global listeners and a
 * throttle handle alive for the life of the page with no way to release them.
 *
 * Resolving `browser.*` at subscribe time keeps the module free of load-order
 * side effects and makes the whole thing tear down with its last consumer.
 */
const viewport = {
    listeners: /** @type {Function[]} */ ([]),
    /** @type {(() => void)[]} */
    cleanups: [],

    /**
     * Register a callback for viewport changes
     *
     * @param {Function} listener - Function to call when viewport changes
     * @returns {Function} - Function to remove the listener
     */
    addListener(listener) {
        this.listeners.push(listener);
        if (this.listeners.length === 1) {
            this.subscribe();
        }
        return () => {
            const index = this.listeners.indexOf(listener);
            if (index !== -1) {
                this.listeners.splice(index, 1);
            }
            if (!this.listeners.length) {
                this.unsubscribe();
            }
        };
    },

    subscribe() {
        if (typeof window === "undefined") {
            return;
        }
        const throttledUpdate = throttleForAnimation(() => this.notifyListeners());
        this.cleanups.push(() => throttledUpdate.cancel());

        const { visualViewport, navigator } = browser;
        if (visualViewport) {
            visualViewport.addEventListener("resize", throttledUpdate);
            this.cleanups.push(() =>
                visualViewport.removeEventListener("resize", throttledUpdate),
            );
        }

        if (isVirtualKeyboardSupported()) {
            const keyboard = /** @type {any} */ (navigator).virtualKeyboard;
            keyboard.addEventListener("geometrychange", throttledUpdate);
            this.cleanups.push(() =>
                keyboard.removeEventListener("geometrychange", throttledUpdate),
            );
        }

        browser.addEventListener("resize", throttledUpdate);
        this.cleanups.push(() =>
            browser.removeEventListener("resize", throttledUpdate),
        );
    },

    unsubscribe() {
        for (const cleanup of this.cleanups.splice(0)) {
            cleanup();
        }
    },

    notifyListeners() {
        for (const listener of [...this.listeners]) {
            listener();
        }
    },
};

/**
 * Get current viewport dimensions
 * Takes into account VirtualKeyboard API if available
 *
 * @returns {{ width: number, height: number }} - width and height in pixels
 */
export function getViewportDimensions() {
    return {
        width: browser.visualViewport?.width ?? browser.innerWidth,
        height: browser.visualViewport?.height ?? browser.innerHeight,
    };
}

/**
 * Register a callback for viewport dimension changes
 * This will trigger for regular viewport changes and virtual keyboard visibility changes
 *
 * @param {Function} callback - Function to call on viewport change
 * @returns {Function} - Function to remove the listener
 */
function onViewportChange(callback) {
    return viewport.addListener(callback);
}

/**
 * OWL hook to use viewport change tracking in components
 * Automatically cleans up listener when component is unmounted
 *
 * @param {Function} callback - Function to call when viewport changes
 */
export function useViewportChange(callback) {
    const removeListener = onViewportChange(callback);
    onWillUnmount(() => removeListener());
}
