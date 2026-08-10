import { describe, expect, test } from "@odoo/hoot";
import { mockTimeZone } from "@odoo/hoot-mock";
import { makeMockEnv } from "@web/../tests/web_test_helpers";
import {
    getInRangeProviderOptions,
    matchInRangeProviderOption,
    resolveInRangeProviderOption,
} from "@web/core/tree/in_range_providers";

import { setDateRanges } from "@date_range/js/date_range_provider";
import "@date_range/js/date_range_provider";

describe.current.tags("headless");

const RANGES = [
    {
        id: 7,
        name: "Q1 2030",
        date_start: "2030-01-01",
        date_end: "2030-03-31",
        type_id: [3, "Quarter"],
    },
    {
        id: 8,
        name: "H1 2030",
        date_start: "2030-01-01",
        date_end: "2030-06-30",
        type_id: [4, "Half"],
    },
];

function withRanges(ranges = RANGES) {
    setDateRanges(ranges);
}

test("periods are offered, grouped by their type", async () => {
    await makeMockEnv();
    withRanges();
    const options = getInRangeProviderOptions("date");
    expect(options.map((o) => o.label)).toEqual(["Q1 2030", "H1 2030"]);
    // The provider's own label heads the group, subdivided by the range type,
    // so two providers cannot produce colliding headings.
    expect(options.map((o) => o.group)).toEqual([
        "Periods / Quarter",
        "Periods / Half",
    ]);
});

test("a non-date field is offered no periods", async () => {
    await makeMockEnv();
    withRanges();
    expect(getInRangeProviderOptions("char")).toEqual([]);
    expect(getInRangeProviderOptions("integer")).toEqual([]);
});

test("picking a period on a date field yields its plain dates", async () => {
    await makeMockEnv();
    withRanges();
    expect(resolveInRangeProviderOption("date_range:7", "date")).toEqual([
        "2030-01-01",
        "2030-03-31",
    ]);
});

test("picking a period on a datetime field covers both of its end days", async () => {
    await makeMockEnv();
    mockTimeZone(0);
    withRanges();
    // Start at the first instant of the start day, end at the last of the end
    // day. Swapped, the filter silently loses almost two days.
    expect(resolveInRangeProviderOption("date_range:7", "datetime")).toEqual([
        "2030-01-01 00:00:00",
        "2030-03-31 23:59:59",
    ]);
});

test("the period's end days follow the user's timezone", async () => {
    await makeMockEnv();
    mockTimeZone(2);
    withRanges();
    const [start, end] = resolveInRangeProviderOption("date_range:7", "datetime");
    // Two hours east: local midnight is 22:00 UTC the day before, and the last
    // local instant of 31 March is 21:59:59 UTC on that same day.
    expect(start).toBe("2029-12-31 22:00:00");
    expect(end).toBe("2030-03-31 21:59:59");
    // And the round trip still names the period it came from -- the bug this
    // guards is reading the bound back by slicing its first ten characters,
    // which lands on the wrong day for any user east of Greenwich.
    expect(matchInRangeProviderOption("datetime", start, end)).toBe("date_range:7");
});

test("a stored range whose bounds match a period is offered back as one", async () => {
    await makeMockEnv();
    withRanges();
    expect(matchInRangeProviderOption("date", "2030-01-01", "2030-03-31")).toBe(
        "date_range:7",
    );
    expect(matchInRangeProviderOption("date", "2030-01-01", "2030-06-30")).toBe(
        "date_range:8",
    );
});

test("bounds naming no period stay a custom range", async () => {
    await makeMockEnv();
    withRanges();
    expect(matchInRangeProviderOption("date", "2030-01-02", "2030-03-31")).toBe(null);
    expect(matchInRangeProviderOption("date", false, false)).toBe(null);
    // A dynamic bound is an expression object, not a string; it names no period
    // and must not be compared as one.
    expect(
        matchInRangeProviderOption("date", { _expr: "context_today()" }, "2030-03-31"),
    ).toBe(null);
});

test("no loaded ranges degrades to the built-in value types", async () => {
    await makeMockEnv();
    withRanges([]);
    expect(getInRangeProviderOptions("date")).toEqual([]);
    expect(matchInRangeProviderOption("date", "2030-01-01", "2030-03-31")).toBe(null);
    expect(resolveInRangeProviderOption("date_range:7", "date")).toBe(null);
});

test("an unknown option id resolves to nothing", async () => {
    await makeMockEnv();
    withRanges();
    expect(resolveInRangeProviderOption("date_range:999", "date")).toBe(null);
    expect(resolveInRangeProviderOption("something_else:7", "date")).toBe(null);
});
