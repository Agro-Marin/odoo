// @ts-check
/** @odoo-module native */

/** @module @web/ui/viewport */

import { browser } from "@web/core/browser/browser";

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
 * Lower bound of every size above XS, ascending. A viewport's size is how many
 * of these it clears. Pairing each band's own `min-width` with its `max-width`
 * instead leaves the reals between them matching nothing -- a 575px viewport at
 * a fractional device scale factor is 575.xx and clears neither `max-width:
 * 575px` nor `min-width: 576px` -- which yielded a size of -1.
 * @type {number[]}
 */
const SIZE_THRESHOLDS = MEDIAS_BREAKPOINTS.map(({ minWidth }) => minWidth).filter(
    (minWidth) => minWidth !== undefined,
);

/**
 * @returns {MediaQueryList[]}
 */
export function getMediaQueryLists() {
    return SIZE_THRESHOLDS.map((minWidth) =>
        browser.matchMedia(`(min-width: ${minWidth}px)`),
    );
}

/**
 * @param {MediaQueryList[]} medias
 * @returns {number}
 */
export function sizeOf(medias) {
    let size = SIZES.XS;
    for (const media of medias) {
        if (media.matches) {
            size++;
        }
    }
    return size;
}

/**
 * @type {MediaQueryList[]}
 */
let sharedMedias = [];
/**
 * @type {((query: string) => MediaQueryList) | null}
 */
let sharedMatchMedia = null;

/**
 * A point-in-time reading of the viewport, for code that has no env: tour steps,
 * website interactions, anything outside a component.
 *
 * NOT reactive, and that is the whole distinction from the `ui` service. Both
 * read the same live media queries so they can never disagree on the value, but
 * only `ui.size` / `ui.isSmall` sit in a `reactive` and re-render their readers
 * on a resize. Called from a component, these two answer correctly once and then
 * never again -- reach for `useService("ui")` there instead.
 */
export const utils = {
    getSize() {
        if (sharedMatchMedia !== browser.matchMedia) {
            sharedMatchMedia = browser.matchMedia;
            sharedMedias = getMediaQueryLists();
        }
        return sizeOf(sharedMedias);
    },
    isSmall(/** @type {{ size?: number }} */ ui = {}) {
        return (ui.size ?? utils.getSize()) <= SIZES.SM;
    },
};
