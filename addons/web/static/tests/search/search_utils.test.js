// @ts-check

import { beforeEach, describe, expect, test } from "@odoo/hoot";
import { mockDate, mockTimeZone } from "@odoo/hoot-mock";
import {
    allowTranslations,
    patchTranslations,
    patchWithCleanup,
} from "@web/../tests/web_test_helpers";
import { Domain } from "@web/core/domain";
import { localization } from "@web/core/l10n/localization";
import { luxon } from "@web/core/l10n/luxon";
import {
    BACKEND_INTERVAL_OPTIONS,
    constructDateDomain,
    getMonthPeriodOptions,
    getPeriodOptions,
    rankInterval,
} from "@web/search/utils/dates";

describe.current.tags("headless");

/** @type {Record<string, any>} */
const dateSearchItem = {
    fieldName: "date_field",
    fieldType: "date",
    optionsParams: {
        /** @type {Record<string, any>[]} */
        customOptions: [],
        endMonth: 0,
        endYear: 0,
        startMonth: -2,
        startYear: -2,
    },
    type: "dateFilter",
};
const dateTimeSearchItem = {
    ...dateSearchItem,
    fieldType: "datetime",
};

beforeEach(() => {
    mockTimeZone(0);
    patchWithCleanup(localization, { direction: "ltr" });
    allowTranslations();
});

test("construct simple domain based on date field (no comparisonOptionId)", () => {
    mockDate("2020-06-01T13:00:00");
    const referenceMoment = luxon.DateTime.local();

    let domain = constructDateDomain(referenceMoment, dateSearchItem, []);
    expect(domain).toEqual({
        domain: new Domain(`[]`),
        description: "",
    });

    domain = constructDateDomain(referenceMoment, dateSearchItem, ["month", "year"]);
    expect(domain).toEqual({
        domain: new Domain(
            `["&", ("date_field", ">=", "2020-06-01"), ("date_field", "<=", "2020-06-30")]`,
        ),
        description: "June 2020",
    });

    domain = constructDateDomain(referenceMoment, dateSearchItem, [
        "second_quarter",
        "year",
    ]);
    expect(domain).toEqual({
        domain: new Domain(
            `["&", ("date_field", ">=", "2020-04-01"), ("date_field", "<=", "2020-06-30")]`,
        ),
        description: "Q2 2020",
    });

    domain = constructDateDomain(referenceMoment, dateSearchItem, ["year"]);
    expect(domain).toEqual({
        domain: new Domain(
            `["&", ("date_field", ">=", "2020-01-01"), ("date_field", "<=", "2020-12-31")]`,
        ),
        description: "2020",
    });
});

test("construct simple domain based on date field (no comparisonOptionId) - UTC+2", () => {
    mockTimeZone(2);
    mockDate("2020-06-01T00:00:00");
    const referenceMoment = luxon.DateTime.local();

    let domain = constructDateDomain(referenceMoment, dateSearchItem, []);
    expect(domain).toEqual({
        domain: new Domain(`[]`),
        description: "",
    });

    domain = constructDateDomain(referenceMoment, dateSearchItem, ["month", "year"]);
    expect(domain).toEqual({
        domain: new Domain(
            `["&", ("date_field", ">=", "2020-06-01"), ("date_field", "<=", "2020-06-30")]`,
        ),
        description: "June 2020",
    });

    domain = constructDateDomain(referenceMoment, dateSearchItem, [
        "second_quarter",
        "year",
    ]);
    expect(domain).toEqual({
        domain: new Domain(
            `["&", ("date_field", ">=", "2020-04-01"), ("date_field", "<=", "2020-06-30")]`,
        ),
        description: "Q2 2020",
    });

    domain = constructDateDomain(referenceMoment, dateSearchItem, ["year"]);
    expect(domain).toEqual({
        domain: new Domain(
            `["&", ("date_field", ">=", "2020-01-01"), ("date_field", "<=", "2020-12-31")]`,
        ),
        description: "2020",
    });
});

test("construct simple domain based on datetime field (no comparisonOptionId)", () => {
    mockDate("2020-06-01T13:00:00");
    const referenceMoment = luxon.DateTime.local();

    let domain = constructDateDomain(referenceMoment, dateTimeSearchItem, [
        "month",
        "year",
    ]);
    expect(domain).toEqual({
        domain: new Domain(
            `["&", ("date_field", ">=", "2020-06-01 00:00:00"), ("date_field", "<=", "2020-06-30 23:59:59")]`,
        ),
        description: "June 2020",
    });

    domain = constructDateDomain(referenceMoment, dateTimeSearchItem, [
        "second_quarter",
        "year",
    ]);
    expect(domain).toEqual({
        domain: new Domain(
            `["&", ("date_field", ">=", "2020-04-01 00:00:00"), ("date_field", "<=", "2020-06-30 23:59:59")]`,
        ),
        description: "Q2 2020",
    });

    domain = constructDateDomain(referenceMoment, dateTimeSearchItem, ["year"]);
    expect(domain).toEqual({
        domain: new Domain(
            `["&", ("date_field", ">=", "2020-01-01 00:00:00"), ("date_field", "<=", "2020-12-31 23:59:59")]`,
        ),
        description: "2020",
    });
});

test("construct simple domain based on datetime field (no comparisonOptionId) - UTC+2", () => {
    mockTimeZone(2);
    mockDate("2020-06-01T00:00:00");
    const referenceMoment = luxon.DateTime.local();

    let domain = constructDateDomain(referenceMoment, dateTimeSearchItem, [
        "month",
        "year",
    ]);
    expect(domain).toEqual({
        domain: new Domain(
            `["&", ("date_field", ">=", "2020-05-31 22:00:00"), ("date_field", "<=", "2020-06-30 21:59:59")]`,
        ),
        description: "June 2020",
    });

    domain = constructDateDomain(referenceMoment, dateTimeSearchItem, [
        "second_quarter",
        "year",
    ]);
    expect(domain).toEqual({
        domain: new Domain(
            `["&", ("date_field", ">=", "2020-03-31 22:00:00"), ("date_field", "<=", "2020-06-30 21:59:59")]`,
        ),
        description: "Q2 2020",
    });

    domain = constructDateDomain(referenceMoment, dateTimeSearchItem, ["year"]);
    expect(domain).toEqual({
        domain: new Domain(
            `["&", ("date_field", ">=", "2019-12-31 22:00:00"), ("date_field", "<=", "2020-12-31 21:59:59")]`,
        ),
        description: "2020",
    });
});

test("construct domain based on date field (no comparisonOptionId)", () => {
    mockDate("2020-01-01T12:00:00");
    const referenceMoment = luxon.DateTime.local();

    let domain = constructDateDomain(referenceMoment, dateSearchItem, [
        "month",
        "first_quarter",
        "year",
    ]);
    expect(domain).toEqual({
        domain: new Domain(
            "[" +
                `"|", ` +
                `"&", ("date_field", ">=", "2020-01-01"), ("date_field", "<=", "2020-01-31"), ` +
                `"&", ("date_field", ">=", "2020-01-01"), ("date_field", "<=", "2020-03-31")` +
                "]",
        ),
        description: "January 2020/Q1 2020",
    });

    domain = constructDateDomain(referenceMoment, dateSearchItem, [
        "second_quarter",
        "year",
        "year-1",
    ]);
    expect(domain).toEqual({
        domain: new Domain(
            "[" +
                `"|", ` +
                `"&", ("date_field", ">=", "2019-04-01"), ("date_field", "<=", "2019-06-30"), ` +
                `"&", ("date_field", ">=", "2020-04-01"), ("date_field", "<=", "2020-06-30")` +
                "]",
        ),
        description: "Q2 2019/Q2 2020",
    });

    domain = constructDateDomain(referenceMoment, dateSearchItem, [
        "year",
        "month",
        "month-2",
    ]);
    expect(domain).toEqual({
        domain: new Domain(
            "[" +
                `"|", ` +
                `"&", ("date_field", ">=", "2020-01-01"), ("date_field", "<=", "2020-01-31"), ` +
                `"&", ("date_field", ">=", "2020-11-01"), ("date_field", "<=", "2020-11-30")` +
                "]",
        ),
        description: "January 2020/November 2020",
    });
});

test("construct domain based on datetime field (no comparisonOptionId)", () => {
    mockDate("2020-01-01T12:00:00");
    const referenceMoment = luxon.DateTime.local();

    let domain = constructDateDomain(referenceMoment, dateTimeSearchItem, [
        "month",
        "first_quarter",
        "year",
    ]);
    expect(domain).toEqual({
        domain: new Domain(
            "[" +
                `"|", ` +
                `"&", ("date_field", ">=", "2020-01-01 00:00:00"), ("date_field", "<=", "2020-01-31 23:59:59"), ` +
                `"&", ("date_field", ">=", "2020-01-01 00:00:00"), ("date_field", "<=", "2020-03-31 23:59:59")` +
                "]",
        ),
        description: "January 2020/Q1 2020",
    });

    domain = constructDateDomain(referenceMoment, dateTimeSearchItem, [
        "second_quarter",
        "year",
        "year-1",
    ]);
    expect(domain).toEqual({
        domain: new Domain(
            "[" +
                `"|", ` +
                `"&", ("date_field", ">=", "2019-04-01 00:00:00"), ("date_field", "<=", "2019-06-30 23:59:59"), ` +
                `"&", ("date_field", ">=", "2020-04-01 00:00:00"), ("date_field", "<=", "2020-06-30 23:59:59")` +
                "]",
        ),
        description: "Q2 2019/Q2 2020",
    });

    domain = constructDateDomain(referenceMoment, dateTimeSearchItem, [
        "year",
        "month",
        "month-2",
    ]);
    expect(domain).toEqual({
        domain: new Domain(
            "[" +
                `"|", ` +
                `"&", ("date_field", ">=", "2020-01-01 00:00:00"), ("date_field", "<=", "2020-01-31 23:59:59"), ` +
                `"&", ("date_field", ">=", "2020-11-01 00:00:00"), ("date_field", "<=", "2020-11-30 23:59:59")` +
                "]",
        ),
        description: "January 2020/November 2020",
    });
});

test("Quarter option: custom translation", async () => {
    mockDate("2020-06-01T13:00:00");
    const referenceMoment = luxon.DateTime.local().setLocale("en");
    patchTranslations({ web: { Q2: "Deuxième trimestre de l'an de grâce" } });

    const domain = constructDateDomain(referenceMoment, dateSearchItem, [
        "second_quarter",
        "year",
    ]);
    expect(domain).toEqual({
        domain: new Domain(
            `["&", ("date_field", ">=", "2020-04-01"), ("date_field", "<=", "2020-06-30")]`,
        ),
        description: "Deuxième trimestre de l'an de grâce 2020",
    });
});

test("Quarter option: right to left", async () => {
    mockDate("2020-06-01T13:00:00");
    const referenceMoment = luxon.DateTime.local().setLocale("en");
    patchWithCleanup(localization, { direction: "rtl" });

    const domain = constructDateDomain(referenceMoment, dateSearchItem, [
        "second_quarter",
        "year",
    ]);
    expect(domain).toEqual({
        domain: new Domain(
            `["&", ("date_field", ">=", "2020-04-01"), ("date_field", "<=", "2020-06-30")]`,
        ),
        description: "2020 Q2",
    });
});

test("Quarter option: custom translation and right to left", async () => {
    mockDate("2020-06-01T13:00:00");
    const referenceMoment = luxon.DateTime.local().setLocale("en");
    patchWithCleanup(localization, { direction: "rtl" });
    patchTranslations({ web: { Q2: "2e Trimestre" } });

    const domain = constructDateDomain(referenceMoment, dateSearchItem, [
        "second_quarter",
        "year",
    ]);
    expect(domain).toEqual({
        domain: new Domain(
            `["&", ("date_field", ">=", "2020-04-01"), ("date_field", "<=", "2020-06-30")]`,
        ),
        description: "2020 2e Trimestre",
    });
});

describe("month period options", () => {
    const defaultWindow = { startYear: -2, endYear: 0, startMonth: -2, endMonth: 0 };

    test("default window: three months, newest first, current-year defaults", () => {
        mockDate("2020-06-01T13:00:00");
        const referenceMoment = luxon.DateTime.local().setLocale("en");

        const options = getMonthPeriodOptions(referenceMoment, defaultWindow);

        expect(options.map((o) => o.id)).toEqual(["month", "month-1", "month-2"]);
        expect(options.map((o) => o.description)).toEqual(["June", "May", "April"]);
        expect(options.map((o) => o.defaultYearId)).toEqual(["year", "year", "year"]);
    });

    test("window crossing into the previous year keeps the real year offset", () => {
        mockDate("2020-01-15T13:00:00");
        const referenceMoment = luxon.DateTime.local().setLocale("en");

        const options = getMonthPeriodOptions(referenceMoment, defaultWindow);

        const december = options.find((o) => o.id === "month-1");
        expect(december.description).toBe("December");
        expect(december.defaultYearId).toBe("year-1");
    });

    test("month window spilling past the year window snaps into the window", () => {
        mockDate("2020-12-15T13:00:00");
        const referenceMoment = luxon.DateTime.local().setLocale("en");

        const options = getMonthPeriodOptions(referenceMoment, {
            ...defaultWindow,
            startMonth: 0,
            endMonth: 2,
        });

        const january = options.find((o) => o.id === "month+1");
        expect(january.description).toBe("January");
        expect(january.defaultYearId).toBe("year");
    });

    test("future year window: year options stay in the window and defaults resolve", () => {
        mockDate("2017-01-07T03:00:00");
        const referenceMoment = luxon.DateTime.local().setLocale("en");

        const options = getPeriodOptions(referenceMoment, {
            startYear: 2,
            endYear: 4,
            startMonth: -2,
            endMonth: 0,
            customOptions: [],
        });

        expect(
            options.filter((o) => o.granularity === "year").map((o) => o.id),
        ).toEqual(["year+4", "year+3", "year+2"]);
        for (const option of options.filter((o) => o.granularity === "month")) {
            expect(option.defaultYearId).toBe("year+2");
            expect(options.some((o) => o.id === option.defaultYearId)).toBe(true);
        }
    });
});

test("custom period options are OR'd, not silently reduced to the first", () => {
    mockDate("2020-06-01T13:00:00");
    const referenceMoment = luxon.DateTime.local();
    const searchItem = {
        ...dateSearchItem,
        domain: "[]",
        optionsParams: {
            ...dateSearchItem.optionsParams,
            customOptions: [
                { id: "custom_a", description: "A", domain: `[("foo", "=", "a")]` },
                { id: "custom_b", description: "B", domain: `[("foo", "=", "b")]` },
            ],
        },
    };

    expect(constructDateDomain(referenceMoment, searchItem, ["custom_a"])).toEqual({
        description: "A",
        domain: new Domain(`[("foo", "=", "a")]`),
    });
    expect(
        constructDateDomain(referenceMoment, searchItem, ["custom_a", "custom_b"]),
    ).toEqual({
        description: "A/B",
        domain: new Domain(`["|", ("foo", "=", "a"), ("foo", "=", "b")]`),
    });
});

describe("rankInterval", () => {
    test("orders the intervals coarsest first", () => {
        const ids = ["hour", "day", "week", "month", "quarter", "year"];
        expect([...ids].sort((a, b) => rankInterval(a) - rankInterval(b))).toEqual([
            "year",
            "quarter",
            "month",
            "week",
            "day",
            "hour",
        ]);
    });

    test("an unknown id ranks -1, ahead of every real interval", () => {
        expect(rankInterval("nope")).toBe(-1);
        expect(rankInterval("year")).toBeGreaterThan(rankInterval("nope"));
    });

    test("every declared interval has a distinct rank", () => {
        const ranks = Object.keys(BACKEND_INTERVAL_OPTIONS).map(rankInterval);
        expect(new Set(ranks).size).toBe(ranks.length);
        expect(ranks).not.toInclude(-1);
    });
});

describe("getPeriodOptions caching", () => {
    const params = () => ({
        startYear: -2,
        endYear: 0,
        startMonth: -2,
        endMonth: 0,
        customOptions: [],
    });

    test("the same window and moment answer the same array", () => {
        mockDate("2020-06-01T13:00:00");
        const referenceMoment = luxon.DateTime.local();
        const optionsParams = params();

        const first = getPeriodOptions(referenceMoment, optionsParams);
        const second = getPeriodOptions(referenceMoment, optionsParams);

        expect(first).toBe(second);
        expect(first.length).toBe(10);
    });

    test("a different window is not served from another window's entry", () => {
        mockDate("2020-06-01T13:00:00");
        const referenceMoment = luxon.DateTime.local();

        const narrow = getPeriodOptions(referenceMoment, params());
        const wide = getPeriodOptions(referenceMoment, { ...params(), startYear: -5 });

        expect(narrow).not.toBe(wide);
        expect(wide.length).toBe(13);
    });

    test("a different reference moment invalidates the entry", () => {
        const optionsParams = params();
        mockDate("2020-06-01T13:00:00");
        const first = getPeriodOptions(luxon.DateTime.local(), optionsParams);
        mockDate("2021-06-01T13:00:00");
        const second = getPeriodOptions(luxon.DateTime.local(), optionsParams);

        expect(first).not.toBe(second);
        expect(second.length).toBe(first.length);
        expect(second.map((o) => o.description)).not.toEqual(
            first.map((o) => o.description),
        );
    });

    test("the shared array and its options are frozen", () => {
        mockDate("2020-06-01T13:00:00");
        const options = getPeriodOptions(luxon.DateTime.local(), params());

        expect(Object.isFrozen(options)).toBe(true);
        expect(Object.isFrozen(options[0])).toBe(true);
    });
});
