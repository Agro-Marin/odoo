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

const viewport = {
    listeners: /** @type {Function[]} */ ([]),

    /**
     * Register a callback for viewport changes
     *
     * @param {Function} listener - Function to call when viewport changes
     * @returns {Function} - Function to remove the listener
     */
    addListener(listener) {
        this.listeners.push(listener);
        return () => {
            const index = this.listeners.indexOf(listener);
            if (index !== -1) {
                this.listeners.splice(index, 1);
            }
        };
    },

    notifyListeners() {
        this.listeners.forEach((listener) => listener());
    },
};

if (typeof window !== "undefined") {
    const throttledUpdate = throttleForAnimation(() => viewport.notifyListeners());

    if (browser.visualViewport) {
        browser.visualViewport.addEventListener("resize", throttledUpdate);
    }

    if (isVirtualKeyboardSupported()) {
        /** @type {any} */ (browser.navigator).virtualKeyboard.addEventListener(
            "geometrychange",
            throttledUpdate,
        );
    }

    // Fallback to window resize for browsers without VisualViewport or VirtualKeyboard
    browser.addEventListener("resize", throttledUpdate);
}

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
