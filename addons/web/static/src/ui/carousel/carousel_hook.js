// @ts-check
/** @odoo-module native */

import { onWillDestroy, useState } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { clamp } from "@web/core/utils/format/numbers";

/**
 * @typedef {{
 * count: () => number;
 * startIndex?: number;
 * interval?: number;
 * wrap?: boolean;
 * }} CarouselParams
 */

/**
 * @param {CarouselParams} params
 */
export function useCarousel({ count, startIndex = 0, interval = 0, wrap = true }) {
    const stored = useState({ index: startIndex });

    /**
     * @returns {number}
     */
    const activeIndex = () => {
        const total = count();
        return total <= 0 ? 0 : clamp(stored.index, 0, total - 1);
    };

    /** @param {number} target */
    const goTo = (target) => {
        const total = count();
        if (total <= 0) {
            stored.index = 0;
        } else {
            stored.index = wrap
                ? ((target % total) + total) % total
                : clamp(target, 0, total - 1);
        }
    };

    if (interval > 0) {
        const timer = browser.setInterval(() => {
            if (!document.hidden) {
                goTo(activeIndex() + 1);
            }
        }, interval);
        onWillDestroy(() => browser.clearInterval(timer));
    }

    return {
        state: {
            get index() {
                return activeIndex();
            },
            set index(value) {
                goTo(value);
            },
        },
        goTo,
        next: () => goTo(activeIndex() + 1),
        previous: () => goTo(activeIndex() - 1),
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
