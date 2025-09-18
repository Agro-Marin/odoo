// @ts-check

/**
 * Tests for errors.js.
 *
 * FetchRecordError calls _t() in its constructor, which requires a full
 * mock environment (localization service). Tests use makeMockEnv() per test.
 *
 * The module-level error handler registration in the Odoo registry is
 * not tested here — that requires a notification service.
 */

import { describe, expect, test } from "@odoo/hoot";
import { makeMockEnv } from "@web/../tests/web_test_helpers";
import { FetchRecordError } from "@web/model/relational_model/errors";

describe("FetchRecordError", () => {
    test("is an instance of Error", async () => {
        await makeMockEnv();
        const err = new FetchRecordError([1, 2]);
        expect(err).toBeInstanceOf(Error);
    });

    test("stores resIds on the instance", async () => {
        await makeMockEnv();
        const err = new FetchRecordError([5, 10, 15]);
        expect(err.resIds).toEqual([5, 10, 15]);
    });

    test("message is a non-empty string", async () => {
        await makeMockEnv();
        const err = new FetchRecordError([42]);
        expect(typeof err.message).toBe("string");
        expect(err.message.length).toBeGreaterThan(0);
    });

    test("FetchRecordError is distinguishable from plain Error", async () => {
        await makeMockEnv();
        const fetchErr = new FetchRecordError([1]);
        const plainErr = new Error("plain");
        expect(fetchErr instanceof FetchRecordError).toBe(true);
        expect(plainErr instanceof FetchRecordError).toBe(false);
    });
});
