// @ts-check
/** @odoo-module native */

import { onWillUnmount } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { isVirtualKeyboardSupported } from "@web/core/browser/feature_detection";
import { throttleForAnimation } from "@web/core/utils/timing";

const viewport = {
    listeners: /** @type {Function[]} */ ([]),
    /** @type {(() => void)[]} */
    cleanups: [],

    /**
     * @param {Function} listener
     * @returns {Function}
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
 * @returns {{ width: number, height: number }}
 */
export function getViewportDimensions() {
    return {
        width: browser.visualViewport?.width ?? browser.innerWidth,
        height: browser.visualViewport?.height ?? browser.innerHeight,
    };
}

/**
 * @param {Function} callback
 * @returns {Function}
 */
function onViewportChange(callback) {
    return viewport.addListener(callback);
}

/**
 * @param {Function} callback
 */
export function useViewportChange(callback) {
    const removeListener = onViewportChange(callback);
    onWillUnmount(() => removeListener());
}
