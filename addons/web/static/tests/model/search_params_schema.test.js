// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import {
    getSearchParamsIssues,
    SEARCH_PARAMS_SCHEMA,
} from "@web/model/search_params_schema";

describe.current.tags("headless");

test("valid full payload passes", () => {
    const issues = getSearchParamsIssues({
        context: { lang: "en_US" },
        domain: [["name", "=", "Foo"]],
        groupBy: ["partner_id"],
        orderBy: [{ name: "id", asc: true }],
    });
    expect(issues).toEqual([]);
});

test("undefined values for every key (the production no-search-model load) pass", () => {
    expect(
        getSearchParamsIssues({
            context: undefined,
            domain: undefined,
            groupBy: undefined,
            orderBy: undefined,
        }),
    ).toEqual([]);
});

test("empty payload (all-optional) passes", () => {
    expect(getSearchParamsIssues({})).toEqual([]);
});

test("non-object payload is rejected", () => {
    expect(getSearchParamsIssues(null)).toEqual([
        "search params must be a plain object",
    ]);
    expect(getSearchParamsIssues(undefined)).toEqual([
        "search params must be a plain object",
    ]);
    expect(getSearchParamsIssues("foo")).toEqual([
        "search params must be a plain object",
    ]);
});

test("orderBy missing required 'name' is flagged", () => {
    const issues = getSearchParamsIssues({
        orderBy: [{ asc: true }],
    });
    expect(issues.length).toBeGreaterThan(0);
});

test("groupBy of wrong element type is flagged", () => {
    const issues = getSearchParamsIssues({
        groupBy: [42, "ok"],
    });
    expect(issues.length).toBeGreaterThan(0);
});

test("fields outside the SEARCH_KEYS contract are flagged as unknown", () => {
    const issues = getSearchParamsIssues({ resId: 7 });
    expect(issues.length).toBe(1);
    expect(issues[0]).toMatch(/unknown field 'resId'/);
});

test("unknown field is flagged with a remediation hint", () => {
    const issues = getSearchParamsIssues({
        domain: [],
        somethingNew: "value",
    });
    expect(issues.length).toBe(1);
    expect(issues[0]).toMatch(/unknown field 'somethingNew'/);
    expect(issues[0]).toMatch(/SEARCH_PARAMS_SCHEMA/);
});

test("multiple unknown fields each surface as own issue", () => {
    const issues = getSearchParamsIssues({
        domain: [],
        foo: 1,
        bar: 2,
    });
    expect(issues.length).toBeGreaterThanOrEqual(2);
    const text = issues.join("\n");
    expect(text).toMatch(/foo/);
    expect(text).toMatch(/bar/);
});

test("schema enumerates exactly the SEARCH_KEYS contract", () => {
    expect(Object.keys(SEARCH_PARAMS_SCHEMA).toSorted()).toEqual([
        "context",
        "domain",
        "groupBy",
        "orderBy",
    ]);
});
