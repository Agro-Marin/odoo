// @ts-check
/** @odoo-module native */

/** @module @web/ui/viewport - Responsive breakpoints and the service-free size helpers built on them */

export const SIZES = { XS: 0, SM: 1, MD: 2, LG: 3, XL: 4, XXL: 5 };

export const MEDIAS_BREAKPOINTS = [
    { maxWidth: 575 },
    { minWidth: 576, maxWidth: 767 },
    { minWidth: 768, maxWidth: 991 },
    { minWidth: 992, maxWidth: 1199 },
    { minWidth: 1200, maxWidth: 1399 },
    { minWidth: 1400 },
];

/**
 * Build the `MediaQueryList`s matching `MEDIAS_BREAKPOINTS`.
 *
 * @returns {MediaQueryList[]}
 */
export function getMediaQueryLists() {
    // `=== undefined`, not falsiness: a breakpoint bound of 0 is a legitimate
    // value that truthiness would read as "no bound".
    return MEDIAS_BREAKPOINTS.map(({ minWidth, maxWidth }) => {
        if (maxWidth === undefined) {
            return window.matchMedia(`(min-width: ${minWidth}px)`);
        }
        if (minWidth === undefined) {
            return window.matchMedia(`(max-width: ${maxWidth}px)`);
        }
        return window.matchMedia(
            `(min-width: ${minWidth}px) and (max-width: ${maxWidth}px)`,
        );
    });
}

/**
 * Breakpoint list backing the service-free `utils.getSize()`, used by the ~40
 * call sites (`Dropdown.isBottomSheet`, snippets, view components, …) that need
 * the current size without holding an env. Built on first use and never
 * listened to: `uiService` owns its own list and its own listeners.
 * @type {MediaQueryList[] | null}
 */
let sharedMedias = null;

export const utils = {
    getSize() {
        sharedMedias ??= getMediaQueryLists();
        return sharedMedias.findIndex((media) => media.matches);
    },
    isSmall(/** @type {{ size?: number }} */ ui = {}) {
        return (ui.size ?? utils.getSize()) <= SIZES.SM;
    },
};
