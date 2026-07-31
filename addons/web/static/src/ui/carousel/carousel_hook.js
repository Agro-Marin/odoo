// @ts-check
/** @odoo-module native */

/** @module @web/ui/carousel/carousel_hook - Slide index state and autoplay for a Bootstrap-styled carousel */

import { onWillDestroy, useState } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";

/**
 * @typedef {{
 *   count: () => number;
 *   startIndex?: number;
 *   interval?: number;
 *   wrap?: boolean;
 * }} CarouselParams
 */

/**
 * Owns the active slide of a carousel, replacing Bootstrap's
 * `data-bs-ride` / `data-bs-slide` / `data-bs-slide-to` data-api.
 *
 * Only the index is managed here; the template renders `active` from it. That
 * rules out Bootstrap's sliding transition, which needs four transient classes
 * applied across two frames against element references — call sites pair this
 * hook with `.carousel-fade`, whose transition follows `active` alone.
 *
 * `count` is a callback because slides usually come from a prop or a record
 * that changes after the hook is set up.
 *
 * @param {CarouselParams} params
 */
export function useCarousel({ count, startIndex = 0, interval = 0, wrap = true }) {
    const state = useState({ index: startIndex });

    /** @param {number} target */
    const goTo = (target) => {
        const total = count();
        if (total <= 0) {
            state.index = 0;
            return;
        }
        state.index = wrap
            ? ((target % total) + total) % total
            : Math.min(Math.max(target, 0), total - 1);
    };

    let timer = null;
    if (interval > 0) {
        timer = browser.setInterval(() => {
            // A backgrounded tab throttles the timer without stopping it, so
            // the slides would otherwise all advance at once on return.
            if (!document.hidden) {
                goTo(state.index + 1);
            }
        }, interval);
        onWillDestroy(() => browser.clearInterval(timer));
    }

    return {
        state,
        goTo,
        next: () => goTo(state.index + 1),
        previous: () => goTo(state.index - 1),
        /** @returns {boolean} */
        get atStart() {
            return state.index <= 0;
        },
        /** @returns {boolean} */
        get atEnd() {
            return state.index >= count() - 1;
        },
    };
}
