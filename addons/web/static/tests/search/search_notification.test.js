// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { patchWithCleanup } from "@web/../tests/web_test_helpers";
import { fireAndForgetNotify } from "@web/search/search_notification";

describe.current.tags("headless");

/** @returns {any[]} */
function captureErrors() {
    /** @type {any[]} */
    const errors = [];
    patchWithCleanup(console, {
        error: (/** @type {any[]} */ ...args) => errors.push(args),
    });
    return errors;
}

describe("fireAndForgetNotify", () => {
    test("a rejection is reported, not left unhandled", async () => {
        const errors = captureErrors();

        fireAndForgetNotify(Promise.reject(new Error("boom")));
        await Promise.resolve();
        await Promise.resolve();

        expect(errors.length).toBe(1);
        expect(errors[0][0]).toInclude("stale");
        expect(errors[0][1].message).toBe("boom");
    });

    test("a rejection does not escape to the caller", async () => {
        const errors = captureErrors();

        expect(fireAndForgetNotify(Promise.reject(new Error("boom")))).toBe(undefined);
        await Promise.resolve();
        await Promise.resolve();

        expect(errors.length).toBe(1);
    });

    test("a settled notification reports nothing", async () => {
        const errors = captureErrors();

        fireAndForgetNotify(Promise.resolve());
        await Promise.resolve();

        expect(errors).toEqual([]);
    });

    test("an early return that notified nothing is accepted", async () => {
        const errors = captureErrors();

        fireAndForgetNotify(undefined);
        await Promise.resolve();

        expect(errors).toEqual([]);
    });
});
