// @ts-check

import { beforeEach, describe, expect, test } from "@odoo/hoot";
import { markup } from "@odoo/owl";
import { allowTranslations, patchWithCleanup } from "@web/../tests/web_test_helpers";
import { currencies } from "@web/core/currency";
import {
    formatBinary,
    formatFieldDate,
    formatFieldDateTime,
    formatFieldFloat,
    formatFloatFactor,
    formatFloatTime,
    formatInteger,
    formatJson,
    formatMany2one,
    formatMany2oneReference,
    formatMonetary,
    formatPercentage,
    formatReference,
    formatText,
    formatX2many,
} from "@web/core/formatters";
import { localization } from "@web/core/l10n/localization";
import { luxon } from "@web/core/l10n/luxon";
import { humanSize } from "@web/core/utils/format/binary";

const { DateTime } = luxon;

describe.current.tags("headless");

beforeEach(() => {
    allowTranslations();
    patchWithCleanup(localization, {
        dateTimeFormat: "MM/dd/yyyy HH:mm:ss",
        dateFormat: "MM/dd/yyyy",
        decimalPoint: ".",
        thousandsSep: ",",
        grouping: [3, 0],
        code: "en_US",
    });
});

test("formatFieldFloat", () => {
    expect(formatFieldFloat(false)).toBe("");
    expect(formatFieldFloat(200)).toBe("200.00");
    expect(formatFieldFloat(200, { trailingZeros: false })).toBe("200");
});

test("formatFieldFloat does not mutate a shared options object across fields", () => {
    const options = {};

    options.field = { digits: [16, 4] };
    expect(formatFieldFloat(1.23456, options)).toBe("1.2346");
    options.field = { digits: [16, 1] };
    expect(formatFieldFloat(1.23456, options)).toBe("1.2");

    expect(options.digits).toBe(undefined, {
        message:
            "formatFieldFloat must not write digits back into its options argument",
    });
    expect(options.minDigits).toBe(undefined, {
        message:
            "formatFieldFloat must not write minDigits back into its options argument",
    });

    const factorOptions = { factor: 2, field: { digits: [16, 3] } };
    expect(formatFloatFactor(1.5, factorOptions)).toBe("3.000");
    factorOptions.field = { digits: [16, 1] };
    expect(formatFloatFactor(1.5, factorOptions)).toBe("3.0");
    expect(factorOptions.digits).toBe(undefined);
});

test("formatFloatFactor", () => {
    expect(formatFloatFactor(false)).toBe("");
    expect(formatFloatFactor(6000)).toBe("6,000.00");
    expect(formatFloatFactor(6000, { factor: 3 })).toBe("18,000.00");
    expect(formatFloatFactor(6000, { factor: 0.5 })).toBe("3,000.00");
});

test("formatFloatTime", () => {
    expect(formatFloatTime(2)).toBe("02:00");
    expect(formatFloatTime(3.5)).toBe("03:30");
    expect(formatFloatTime(0.25)).toBe("00:15");
    expect(formatFloatTime(0.58)).toBe("00:35");
    expect(formatFloatTime(2 / 60, { displaySeconds: true })).toBe("00:02:00");
    expect(formatFloatTime(2 / 60 + 1 / 3600, { displaySeconds: true })).toBe(
        "00:02:01",
    );
    expect(formatFloatTime(2 / 60 + 2 / 3600, { displaySeconds: true })).toBe(
        "00:02:02",
    );
    expect(formatFloatTime(2 / 60 + 3 / 3600, { displaySeconds: true })).toBe(
        "00:02:03",
    );
    expect(formatFloatTime(0.25, { displaySeconds: true })).toBe("00:15:00");
    expect(formatFloatTime(0.25 + 15 / 3600, { displaySeconds: true })).toBe(
        "00:15:15",
    );
    expect(formatFloatTime(0.25 + 45 / 3600, { displaySeconds: true })).toBe(
        "00:15:45",
    );
    expect(formatFloatTime(56 / 3600, { displaySeconds: true })).toBe("00:00:56");
    expect(formatFloatTime(-0.5)).toBe("-00:30");
    expect(formatFloatTime(-0.004)).toBe("00:00");
    expect(formatFloatTime(-1e-15)).toBe("00:00");
    expect(formatFloatTime(-1e-15, { displaySeconds: true })).toBe("00:00:00");
    expect(formatFloatTime(-0.004, { displaySeconds: true })).toBe("-00:00:14");

    const options = { noLeadingZeroHour: true };
    expect(formatFloatTime(2, options)).toBe("2:00");
    expect(formatFloatTime(3.5, options)).toBe("3:30");
    expect(formatFloatTime(3.5, { ...options, displaySeconds: true })).toBe("3:30:00");
    expect(formatFloatTime(3.5 + 15 / 3600, { ...options, displaySeconds: true })).toBe(
        "3:30:15",
    );
    expect(formatFloatTime(3.5 + 45 / 3600, { ...options, displaySeconds: true })).toBe(
        "3:30:45",
    );
    expect(formatFloatTime(56 / 3600, { ...options, displaySeconds: true })).toBe(
        "0:00:56",
    );
    expect(formatFloatTime(-0.5, options)).toBe("-0:30");
});

test("formatJson", () => {
    expect(formatJson(false)).toBe("");
    expect(formatJson({})).toBe("{}");
    expect(formatJson({ 1: 111 })).toBe('{"1":111}');
    expect(formatJson({ 9: 11, 666: 42 })).toBe('{"9":11,"666":42}');
});

test("formatInteger", () => {
    expect(formatInteger(false)).toBe("");
    expect(formatInteger(0)).toBe("0");

    patchWithCleanup(localization, { grouping: [3, 3, 3, 3] });
    expect(formatInteger(1000000)).toBe("1,000,000");

    patchWithCleanup(localization, { grouping: [3, 2, -1] });
    expect(formatInteger(106500)).toBe("1,06,500");

    patchWithCleanup(localization, { grouping: [1, 2, -1] });
    expect(formatInteger(106500)).toBe("106,50,0");

    const options = { grouping: [2, 0], thousandsSep: "€" };
    expect(formatInteger(6000, options)).toBe("60€00");
});

test("formatInteger past the exponential-notation threshold", () => {
    patchWithCleanup(localization, { grouping: [3, 3, 3, 3] });
    expect(formatInteger(1e20)).toBe("100000000,000,000,000,000");
    expect(formatInteger(1e21)).toBe("1000000000,000,000,000,000");
    expect(formatInteger(-1e21)).toBe("-1000000000,000,000,000,000");
    expect(formatInteger(1e21)).not.toInclude("e");
});

test("formatMany2one", () => {
    expect(formatMany2one(false)).toBe("");
    expect(formatMany2one([false, "M2O value"])).toBe("M2O value");
    expect(formatMany2one([1, false])).toBe("Unnamed");
    expect(formatMany2one([1, "M2O value"])).toBe("M2O value");
    expect(formatMany2one([1, "M2O value"], { escape: true })).toBe("M2O%20value");
    expect(formatMany2one({ id: false, display_name: "M2O value" })).toBe("M2O value");
    expect(formatMany2one({ id: 1, display_name: false })).toBe("Unnamed");
    expect(formatMany2one({ id: 1, display_name: "M2O value" })).toBe("M2O value");
    expect(formatMany2one({ id: 1, display_name: "M2O value" }, { escape: true })).toBe(
        "M2O%20value",
    );
});

test("formatText", () => {
    expect(formatText(false)).toBe("");
    expect(formatText("value")).toBe("value");
    expect(formatText(1)).toBe("1");
    expect(formatText(1.5)).toBe("1.5");
    expect(formatText(markup`<p>This is a Test</p>`)).toBe("<p>This is a Test</p>");
    expect(formatText([1, 2, 3, 4, 5])).toBe("1,2,3,4,5");
    expect(formatText({ a: 1, b: 2 })).toBe("[object Object]");
});

test("formatX2many", () => {
    expect(String(formatX2many({ currentIds: [] }))).toBe("No records");
    expect(String(formatX2many({ currentIds: [1] }))).toBe("1 record");
    expect(String(formatX2many({ currentIds: [1, 3] }))).toBe("2 records");
});

test("formatMonetary", () => {
    patchWithCleanup(currencies, {
        10: {
            digits: [69, 2],
            position: "after",
            symbol: "€",
        },
        11: {
            digits: [69, 2],
            position: "before",
            symbol: "$",
        },
        12: {
            digits: [69, 2],
            position: "after",
            symbol: "&",
        },
    });

    expect(formatMonetary(false)).toBe("");

    const field = {
        type: "monetary",
        currency_field: "c_x",
    };
    let data = {
        c_x: [11],
        c_y: 12,
    };
    expect(formatMonetary(200, { field, currencyId: 10, data })).toBe("200.00\u00a0€");
    expect(
        formatMonetary(200, { field, currencyId: 10, data, trailingZeros: false }),
    ).toBe("200\u00a0€");
    expect(formatMonetary(200, { field, data })).toBe("$\u00a0200.00");
    expect(formatMonetary(200, { field, currencyField: "c_y", data })).toBe(
        "200.00\u00a0&",
    );

    const floatField = { type: "float" };
    data = {
        currency_id: [11],
    };
    expect(formatMonetary(200, { field: floatField, data })).toBe("$\u00a0200.00");
});

test("formatPercentage", () => {
    expect(formatPercentage(false)).toBe("");
    expect(formatPercentage(0)).toBe("0%");
    expect(formatPercentage(0.5)).toBe("50%");

    expect(formatPercentage(1)).toBe("100%");

    expect(formatPercentage(-0.2)).toBe("-20%");
    expect(formatPercentage(2.5)).toBe("250%");

    expect(formatPercentage(0.125)).toBe("12.5%");
    expect(formatPercentage(0.666666)).toBe("66.67%");
    expect(formatPercentage(125)).toBe("12500%");

    expect(formatPercentage(50, { humanReadable: true })).toBe("5k%");
    expect(formatPercentage(0.5, { noSymbol: true })).toBe("50");

    patchWithCleanup(localization, {
        grouping: [3, 0],
        decimalPoint: ",",
        thousandsSep: ".",
    });
    expect(formatPercentage(0.125)).toBe("12,5%");
    expect(formatPercentage(0.666666)).toBe("66,67%");
});

test("formatReference", () => {
    expect(formatReference(false)).toBe("");
    const value = { resModel: "product", resId: 2, displayName: "Chair" };
    expect(formatReference(value)).toBe("Chair");
});

test("formatMany2oneReference", () => {
    expect(formatMany2oneReference(false)).toBe("");
    expect(formatMany2oneReference({ resId: 9, displayName: "Chair" })).toBe("Chair");
});

test("formatFieldDate", () => {
    expect(formatFieldDate(false)).toBe("");
    expect(
        formatFieldDate(DateTime.fromObject({ day: 22, month: 1, year: 1990 })),
    ).toBe("Jan 22, 1990");
    expect(
        formatFieldDate(DateTime.fromObject({ day: 22, month: 1, year: 1990 }), {
            numeric: true,
        }),
    ).toBe("01/22/1990");
    expect(formatFieldDate(DateTime.fromObject({ day: 22, month: 1 }))).toBe("Jan 22");
});

test("formatFieldDateTime", () => {
    const datetime = DateTime.fromObject({
        day: 22,
        month: 1,
        year: 1990,
        hour: 10,
        minute: 30,
        second: 45,
    });
    expect(formatFieldDateTime(false)).toBe("");
    expect(formatFieldDateTime(datetime)).toBe("Jan 22, 1990, 10:30 AM");
    expect(formatFieldDateTime(datetime, { showDate: false })).toBe("10:30 AM");
    expect(formatFieldDateTime(datetime, { showSeconds: true })).toBe(
        "Jan 22, 1990, 10:30:45 AM",
    );
    expect(formatFieldDateTime(datetime, { showTime: false })).toBe("Jan 22, 1990");
    expect(formatFieldDateTime(datetime, { numeric: true })).toBe(
        "01/22/1990 10:30:45",
    );
    expect(
        formatFieldDateTime(
            DateTime.fromObject({ day: 22, month: 1, hour: 10, minute: 30 }),
        ),
    ).toBe("Jan 22, 10:30 AM");
});

test("numeric formatters agree on absent and non-finite values", () => {
    for (const format of [
        formatFieldFloat,
        formatFloatFactor,
        formatFloatTime,
        formatInteger,
        formatMonetary,
        formatPercentage,
    ]) {
        for (const value of [false, null, undefined, "", NaN, Infinity, -Infinity]) {
            expect(format(value)).toBe("", {
                message: `${format.name}(${String(value)}) should render as empty`,
            });
        }
    }
});

test("humanReadable numeric formatting is guarded too", () => {
    for (const format of [formatFieldFloat, formatInteger]) {
        for (const value of [undefined, null, NaN, Infinity]) {
            expect(format(value, { humanReadable: true })).toBe("", {
                message: `${format.name}(${String(value)}, {humanReadable}) should not throw`,
            });
        }
    }
    expect(formatInteger(1500, { humanReadable: true })).toBe("2k");
    expect(formatFieldFloat(1500, { humanReadable: true, decimals: 1 })).toBe("1.5k");
});

test("formatBinary reports sizes in the same units as every upload widget", () => {
    expect(formatBinary("")).toBe("");
    expect(formatBinary(false)).toBe("");
    expect(formatBinary("1.5 MB")).toBe("1.5 MB");
    expect(formatBinary("a".repeat(1370))).toBe(humanSize(1000));
    expect(formatBinary("a".repeat(1370))).toBe("1000.00 Bytes");
    expect(formatBinary("a".repeat(2740))).toBe("1.95 KB");
});
