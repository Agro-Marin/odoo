// @ts-check
/** @odoo-module native */

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
 * @type {number[]}
 */
const SIZE_THRESHOLDS = MEDIAS_BREAKPOINTS.map(({ minWidth }) => minWidth).filter(
    (minWidth) => minWidth !== undefined,
);

/**
 * @type {MediaQueryList[]}
 */
let sharedMedias = [];
/**
 * @type {((query: string) => MediaQueryList) | null}
 */
let sharedMatchMedia = null;

/**
 * @returns {void}
 */
export function _resetMediaQueryLists() {
    sharedMatchMedia = null;
    sharedMedias = [];
}

/**
 * @returns {MediaQueryList[]}
 */
export function getMediaQueryLists() {
    if (sharedMatchMedia !== browser.matchMedia) {
        sharedMatchMedia = browser.matchMedia;
        sharedMedias = SIZE_THRESHOLDS.map((minWidth) =>
            browser.matchMedia(`(min-width: ${minWidth}px)`),
        );
    }
    return sharedMedias;
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
 * The viewport size, read live from the breakpoint queries on every call. It
 * stays live on purpose: a cache would have to be invalidated by the `change`
 * events, and `getSize` is also asked by callers -- tests among them -- that
 * move the viewport without any event being delivered.
 */
export const utils = {
    getSize() {
        return sizeOf(getMediaQueryLists());
    },
    isSmall(/** @type {{ size?: number }} */ ui = {}) {
        return (ui.size ?? utils.getSize()) <= SIZES.SM;
    },
};
