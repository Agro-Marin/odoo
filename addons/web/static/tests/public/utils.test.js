// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { PairSet, patchDynamicContent } from "@web/public/utils";

describe.current.tags("headless");

describe("PairSet", () => {
    test("can add and delete pairs", () => {
        const pairSet = new PairSet();

        const a = {};
        const b = {};
        expect(pairSet.has(a, b)).toBe(false);
        pairSet.add(a, b);
        expect(pairSet.has(a, b)).toBe(true);
        pairSet.delete(a, b);
        expect(pairSet.has(a, b)).toBe(false);
    });

    test("can add and delete pairs with the same first element", () => {
        const pairSet = new PairSet();

        const a = {};
        const b = {};
        const c = {};
        expect(pairSet.has(a, b)).toBe(false);
        expect(pairSet.has(a, c)).toBe(false);
        pairSet.add(a, b);
        expect(pairSet.has(a, b)).toBe(true);
        expect(pairSet.has(a, c)).toBe(false);
        pairSet.add(a, c);
        expect(pairSet.has(a, b)).toBe(true);
        expect(pairSet.has(a, c)).toBe(true);
        pairSet.delete(a, c);
        expect(pairSet.has(a, b)).toBe(true);
        expect(pairSet.has(a, c)).toBe(false);
        pairSet.delete(a, b);
        expect(pairSet.has(a, b)).toBe(false);
        expect(pairSet.has(a, c)).toBe(false);
    });

    test("do not duplicated pairs", () => {
        const pairSet = new PairSet();

        const a = {};
        const b = {};
        expect(pairSet.has(a, b)).toBe(false);
        pairSet.add(a, b);
        pairSet.add(a, b);
        expect(pairSet.map.get(a)?.size).toBe(1);
        pairSet.delete(a, b);
        expect(pairSet.has(a, b)).toBe(false);
    });

    test("does not keep its first elements alive", () => {
        expect(new PairSet().map).toBeInstanceOf(WeakMap);
    });
});

describe("patch dynamic content", () => {
    test("patch applies new values", () => {
        /** @type {Record<string, Record<string, any>>} */
        const parent = {
            somewhere: {
                "t-att-doNotTouch": 123,
            },
        };
        /** @type {Record<string, Record<string, any>>} */
        const patch = {
            somewhere: {
                "t-att-class": () => ({
                    abc: true,
                }),
                "t-att-xyz": "123",
            },
            elsewhere: {
                "t-att-class": () => ({
                    xyz: true,
                }),
                "t-att-abc": "123",
            },
        };
        patchDynamicContent(parent, patch);
        expect(Object.keys(parent)).toEqual(["somewhere", "elsewhere"]);
        expect(Object.keys(parent.somewhere)).toEqual([
            "t-att-doNotTouch",
            "t-att-class",
            "t-att-xyz",
        ]);
        expect(Object.keys(parent.elsewhere)).toEqual(["t-att-class", "t-att-abc"]);
    });

    test("patch removes undefined values", () => {
        /** @type {Record<string, Record<string, any>>} */
        const parent = {
            somewhere: {
                "t-att-doNotTouch": 123,
                "t-att-removeMe": "abc",
            },
        };
        /** @type {Record<string, Record<string, any>>} */
        const patch = {
            somewhere: {
                "t-att-removeMe": undefined,
            },
        };
        patchDynamicContent(parent, patch);
        expect(parent).toEqual({
            somewhere: {
                "t-att-doNotTouch": 123,
            },
        });
    });

    test("patch combines function outputs", () => {
        /** @type {Record<string, Record<string, any>>} */
        const parent = {
            somewhere: {
                "t-att-style": () => ({
                    doNotTouch: true,
                    changeMe: 10,
                    doubleMe: 100,
                }),
            },
        };
        /** @type {Record<string, Record<string, any>>} */
        const patch = {
            somewhere: {
                "t-att-style": /** @param {any} el @param {any} old */ (el, old) => ({
                    changeMe: 50,
                    doubleMe: old.doubleMe * 2,
                    addMe: 1000,
                }),
            },
        };
        patchDynamicContent(parent, patch);
        expect(parent.somewhere["t-att-style"]()).toEqual({
            doNotTouch: true,
            changeMe: 50,
            doubleMe: 200,
            addMe: 1000,
        });
    });

    test("patch t-on-... provides access to super", () => {
        /** @type {Record<string, Record<string, any>>} */
        const parent = {
            somewhere: {
                "t-on-click": () => {
                    expect.step("base");
                },
            },
        };
        /** @type {Record<string, Record<string, any>>} */
        const patch = {
            somewhere: {
                "t-on-click": /** @param {any} el @param {any} oldFn */ (el, oldFn) => {
                    oldFn();
                    expect.step("patch");
                },
            },
        };
        patchDynamicContent(parent, patch);
        parent.somewhere["t-on-click"]();
        expect.verifySteps(["base", "patch"]);
    });

    test("patch t-on-... does not require knowledge about there being a super", () => {
        /** @type {Record<string, Record<string, any>>} */
        const parent = {};
        /** @type {Record<string, Record<string, any>>} */
        const patch = {
            somewhere: {
                "t-on-click": /** @param {any} el @param {any} oldFn */ (el, oldFn) => {
                    oldFn();
                    expect.step("patch");
                },
            },
        };
        patchDynamicContent(parent, patch);
        parent.somewhere["t-on-click"]();
        expect.verifySteps(["patch"]);
    });
});

test("removing an entry does not leave an empty selector behind", () => {
    /** @type {Record<string, Record<string, any>>} */
    const dynamicContent = {};
    patchDynamicContent(dynamicContent, { ".gone": { "t-on-click": undefined } });
    expect(Object.keys(dynamicContent)).toEqual([]);

    /** @type {Record<string, Record<string, any>>} */
    const existing = { ".kept": { "t-on-click": () => {}, "t-att-a": () => "b" } };
    patchDynamicContent(existing, { ".kept": { "t-on-click": undefined } });
    expect(Object.keys(existing)).toEqual([".kept"]);
    expect(Object.keys(existing[".kept"])).toEqual(["t-att-a"]);
});
