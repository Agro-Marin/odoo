// @ts-check

import { expect, test } from "@odoo/hoot";
import { resize } from "@odoo/hoot-dom";
import {
    getService,
    makeMockEnv,
    patchWithCleanup,
} from "@web/../tests/web_test_helpers";
import { browser } from "@web/core/browser/browser";
import {
    _resetMediaQueryLists,
    getMediaQueryLists,
    MEDIAS_BREAKPOINTS,
    sizeOf,
    SIZES,
    utils,
} from "@web/ui/viewport";

/**
 * @param {() => number} getWidth
 */
function mockMatchMediaAtWidth(getWidth) {
    patchWithCleanup(browser, {
        matchMedia: (/** @type {string} */ query) => {
            const min = Number(query.match(/min-width:\s*(\d+)px/)?.[1]);
            return {
                get matches() {
                    return Number.isNaN(min) ? false : getWidth() >= min;
                },
                addEventListener() {},
                removeEventListener() {},
            };
        },
    });
}

test("SIZES and MEDIAS_BREAKPOINTS describe the same ladder", () => {
    expect(Object.keys(SIZES)).toHaveLength(MEDIAS_BREAKPOINTS.length);
    expect(Object.values(SIZES)).toEqual([0, 1, 2, 3, 4, 5]);

    expect(MEDIAS_BREAKPOINTS.filter((b) => b.minWidth === undefined)).toHaveLength(1);
    expect(MEDIAS_BREAKPOINTS.filter((b) => b.maxWidth === undefined)).toHaveLength(1);
    expect(MEDIAS_BREAKPOINTS[0].minWidth).toBe(undefined);
    expect(MEDIAS_BREAKPOINTS.at(-1).maxWidth).toBe(undefined);

    for (let i = 1; i < MEDIAS_BREAKPOINTS.length; i++) {
        expect(MEDIAS_BREAKPOINTS[i].minWidth).toBe(
            MEDIAS_BREAKPOINTS[i - 1].maxWidth + 1,
        );
    }
});

test("sizeOf counts the matching queries", () => {
    /** @param {number} n */
    const medias = (n) => Array.from({ length: 5 }, (_, i) => ({ matches: i < n }));
    expect(sizeOf(medias(0))).toBe(SIZES.XS);
    expect(sizeOf(medias(1))).toBe(SIZES.SM);
    expect(sizeOf(medias(2))).toBe(SIZES.MD);
    expect(sizeOf(medias(3))).toBe(SIZES.LG);
    expect(sizeOf(medias(4))).toBe(SIZES.XL);
    expect(sizeOf(medias(5))).toBe(SIZES.XXL);
    expect(sizeOf([])).toBe(SIZES.XS);
});

test("getMediaQueryLists hands out one list, rebuilt when matchMedia changes", () => {
    mockMatchMediaAtWidth(() => 800);
    const first = getMediaQueryLists();
    expect(first).toHaveLength(MEDIAS_BREAKPOINTS.length - 1);
    expect(getMediaQueryLists()).toBe(first);
    expect(sizeOf(first)).toBe(SIZES.MD);

    mockMatchMediaAtWidth(() => 1500);
    const second = getMediaQueryLists();
    expect(second).not.toBe(first);
    expect(sizeOf(second)).toBe(SIZES.XXL);
});

test("the ui service and utils.getSize read the same queries", async () => {
    let width = 1000;
    mockMatchMediaAtWidth(() => width);
    await makeMockEnv(undefined, { makeNew: true });
    const ui = /** @type {any} */ (getService("ui"));
    expect(ui.size).toBe(SIZES.LG);
    expect(utils.getSize()).toBe(ui.size);

    width = 1300;
    expect(ui.getSize()).toBe(SIZES.XL);
    expect(utils.getSize()).toBe(SIZES.XL);
});

test("the ui service reads the shared set, not a reference it captured", async () => {
    let width = 1000;
    mockMatchMediaAtWidth(() => width);
    await makeMockEnv(undefined, { makeNew: true });
    const ui = /** @type {any} */ (getService("ui"));
    expect(ui.getSize()).toBe(SIZES.LG);

    _resetMediaQueryLists();
    width = 400;
    expect(ui.getSize()).toBe(SIZES.XS);
    expect(utils.getSize()).toBe(SIZES.XS);
});

test("utils.isSmall prefers the size it is handed", () => {
    mockMatchMediaAtWidth(() => 800);
    expect(utils.getSize()).toBe(SIZES.MD);
    expect(utils.isSmall()).toBe(false);
    expect(utils.isSmall({ size: SIZES.XS })).toBe(true);
    expect(utils.isSmall({ size: SIZES.SM })).toBe(true);
    expect(utils.isSmall({ size: SIZES.MD })).toBe(false);
});

test("_resetMediaQueryLists rebuilds a set matchMedia's identity cannot invalidate", () => {
    mockMatchMediaAtWidth(() => 800);
    const first = getMediaQueryLists();
    expect(getMediaQueryLists()).toBe(first);

    _resetMediaQueryLists();
    const second = getMediaQueryLists();
    expect(second).not.toBe(first);
    expect(sizeOf(second)).toBe(SIZES.MD);
});

test("ui.isSmall follows a viewport change made after the service was built", async () => {
    await resize({ width: 1366 });
    await makeMockEnv(undefined, { makeNew: true });
    const ui = /** @type {any} */ (getService("ui"));
    expect(ui.isSmall).toBe(false);

    await resize({ width: 400 });
    expect(ui.isSmall).toBe(true);

    await resize({ width: 1366 });
    expect(ui.isSmall).toBe(false);
});
