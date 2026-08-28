// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { resize } from "@odoo/hoot-dom";
import { patchWithCleanup } from "@web/../tests/web_test_helpers";
import { browser } from "@web/core/browser/browser";

describe.current.tags("desktop");

describe("the scroll surface", () => {
    test("scrollX and scrollY read through to the window", async () => {
        expect(browser.scrollX).toBe(window.scrollX);
        expect(browser.scrollY).toBe(window.scrollY);
    });

    test("they are getters, so they follow the window rather than snapshot it", async () => {
        await resize({ height: 400, width: 600 });
        expect(browser.scrollX).toBe(window.scrollX);
        expect(browser.scrollY).toBe(window.scrollY);
    });

    test("scrollTo is patchable, which is the point of it being here", async () => {
        /** @type {any[]} */
        const calls = [];
        patchWithCleanup(browser, {
            scrollTo: (/** @type {any[]} */ ...args) => {
                calls.push(args);
            },
        });
        browser.scrollTo({ top: 12, left: 34 });
        expect(calls).toEqual([[{ top: 12, left: 34 }]]);
    });
});

describe("the members that only exist to be patched", () => {
    test("open is bound at capture time, so window is not the seam", async () => {
        /** @type {any[]} */
        const opened = [];
        patchWithCleanup(browser, {
            open: (...args) => {
                opened.push(args);
                return null;
            },
        });
        browser.open("https://example.invalid/", "_blank");
        expect(opened).toEqual([["https://example.invalid/", "_blank"]]);
    });

    test("addEventListener and removeEventListener are patchable as a pair", async () => {
        /** @type {any[]} */
        const added = [];
        /** @type {any[]} */
        const removed = [];
        patchWithCleanup(browser, {
            addEventListener: (/** @type {any} */ type) => added.push(type),
            removeEventListener: (/** @type {any} */ type) => removed.push(type),
        });
        browser.addEventListener("pointermove", () => {});
        browser.removeEventListener("pointermove", () => {});
        expect(added).toEqual(["pointermove"]);
        expect(removed).toEqual(["pointermove"]);
    });
});
