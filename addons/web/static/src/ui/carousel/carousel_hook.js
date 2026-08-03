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
    const stored = useState({ index: startIndex });

    /**
     * The stored index is only valid against the count it was written for, and
     * `count` is a callback precisely because slides come and go. Clamping on
     * read keeps an index that outlived its slide from matching nothing: the
     * template marks a slide active by comparing against this, so a stale index
     * left the carousel showing no slide at all until the user navigated.
     *
     * @returns {number}
     */
    const activeIndex = () => {
        const total = count();
        if (total <= 0) {
            return 0;
        }
        return Math.min(Math.max(stored.index, 0), total - 1);
    };

    /** @param {number} target */
    const goTo = (target) => {
        const total = count();
        if (total <= 0) {
            stored.index = 0;
            return;
        }
        stored.index = wrap
            ? ((target % total) + total) % total
            : Math.min(Math.max(target, 0), total - 1);
    };

    // Reads stay reactive: the getter touches `stored` and whatever `count`
    // reads, both during the consumer's render.
    const state = {
        get index() {
            return activeIndex();
        },
        set index(value) {
            goTo(value);
        },
    };

    if (interval > 0) {
        const timer = browser.setInterval(() => {
            // A backgrounded tab throttles the timer without stopping it, so
            // the slides would otherwise all advance at once on return.
            if (!document.hidden) {
                goTo(activeIndex() + 1);
            }
        }, interval);
        onWillDestroy(() => browser.clearInterval(timer));
    }

    return {
        state,
        goTo,
        next: () => goTo(activeIndex() + 1),
        previous: () => goTo(activeIndex() - 1),
        /** @returns {number} */
        get index() {
            return activeIndex();
        },
        /** @returns {boolean} */
        get atStart() {
            return activeIndex() <= 0;
        },
        /** @returns {boolean} */
        get atEnd() {
            return activeIndex() >= count() - 1;
        },
    };
}
