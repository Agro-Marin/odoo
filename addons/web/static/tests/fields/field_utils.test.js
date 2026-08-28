// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import {
    extractAutosave,
    extractNumericOptions,
    isFalseEmpty,
    parseDimensionAttr,
} from "@web/fields/field_utils";

describe.current.tags("headless");

describe("extractAutosave", () => {
    test("defaults to true, and only an explicit option turns it off", () => {
        expect(extractAutosave({})).toBe(true);
        expect(extractAutosave({ autosave: true })).toBe(true);
        expect(extractAutosave({ autosave: "1" })).toBe(true);
        expect(extractAutosave({ autosave: false })).toBe(false);
        expect(extractAutosave({ autosave: "0" })).toBe(false);
    });

    test("presence is what matters, not truthiness", () => {
        expect(extractAutosave({ autosave: undefined })).toBe(false);
    });
});

describe("isFalseEmpty", () => {
    test("only literal false counts as empty", () => {
        const record = (/** @type {any} */ value) => ({ data: { f: value } });
        expect(isFalseEmpty(/** @type {any} */ (record(false)), "f")).toBe(true);
        expect(isFalseEmpty(/** @type {any} */ (record(0)), "f")).toBe(false);
        expect(isFalseEmpty(/** @type {any} */ (record("")), "f")).toBe(false);
        expect(isFalseEmpty(/** @type {any} */ (record(null)), "f")).toBe(false);
        expect(isFalseEmpty(/** @type {any} */ (record(undefined)), "f")).toBe(false);
    });
});

describe("parseDimensionAttr", () => {
    test("returns a number, or undefined for anything unusable", () => {
        expect(parseDimensionAttr("90")).toBe(90);
        expect(parseDimensionAttr(90)).toBe(90);
        expect(parseDimensionAttr("90px")).toBe(90);
        expect(parseDimensionAttr("")).toBe(undefined);
        expect(parseDimensionAttr(null)).toBe(undefined);
        expect(parseDimensionAttr(undefined)).toBe(undefined);
        expect(parseDimensionAttr("auto")).toBe(undefined);
    });

    test("undefined and not NaN, because the caller spreads the result", () => {
        expect(Number.isNaN(parseDimensionAttr("auto"))).toBe(false);
    });
});

describe("extractNumericOptions", () => {
    test("the defaults every numeric widget inherits", () => {
        expect(extractNumericOptions({ options: {} })).toEqual({
            formatNumber: true,
            humanReadable: false,
            inputType: undefined,
            step: undefined,
            decimals: 0,
        });
    });

    test("enable_formatting is three-state, unlike the rest", () => {
        expect(extractNumericOptions({ options: {} }).formatNumber).toBe(true);
        expect(
            extractNumericOptions({ options: { enable_formatting: false } })
                .formatNumber,
        ).toBe(false);
        expect(
            extractNumericOptions({ options: { enable_formatting: 0 } }).formatNumber,
        ).toBe(false);
        expect(
            extractNumericOptions({ options: { enable_formatting: true } })
                .formatNumber,
        ).toBe(true);
    });

    test("passes the input pass-throughs straight down", () => {
        expect(
            extractNumericOptions({
                options: {
                    human_readable: "1",
                    type: "number",
                    step: 5,
                    decimals: 2,
                },
            }),
        ).toEqual({
            formatNumber: true,
            humanReadable: true,
            inputType: "number",
            step: 5,
            decimals: 2,
        });
    });
});
