// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import {
    SEARCH_PARAMS_SCHEMA,
    validateSearchParams,
} from "@web/model/search_params_schema";

describe.current.tags("headless");

test("valid full payload passes", () => {
    const issues = validateSearchParams({
        context: { lang: "en_US" },
        domain: [["name", "=", "Foo"]],
        groupBy: ["partner_id"],
        orderBy: [{ name: "id", asc: true }],
    });
    expect(issues).toEqual([]);
});

test("undefined values for every key (the production no-search-model load) pass", () => {
    // ``getSearchParams`` always writes the four keys; their values
    // may be undefined when no SearchModel is mounted (e.g. the
    // settings form).  Optional schema entries accept undefined.
    expect(
        validateSearchParams({
            context: undefined,
            domain: undefined,
            groupBy: undefined,
            orderBy: undefined,
        }),
    ).toEqual([]);
});

test("empty payload (all-optional) passes", () => {
    expect(validateSearchParams({})).toEqual([]);
});

test("non-object payload is rejected", () => {
    expect(validateSearchParams(null)).toEqual([
        "search params must be a plain object",
    ]);
    expect(validateSearchParams(undefined)).toEqual([
        "search params must be a plain object",
    ]);
    expect(validateSearchParams("foo")).toEqual([
        "search params must be a plain object",
    ]);
});

test("orderBy missing required 'name' is flagged", () => {
    const issues = validateSearchParams({
        orderBy: [{ asc: true }], // missing 'name'
    });
    expect(issues.length).toBeGreaterThan(0);
    // OWL phrases the error as "name is missing" or similar — we
    // only assert "something complained" so the test stays robust
    // across OWL revisions.
});

test("groupBy of wrong element type is flagged", () => {
    const issues = validateSearchParams({
        groupBy: [42, "ok"], // first entry is a number, not a string
    });
    expect(issues.length).toBeGreaterThan(0);
});

test("fields outside the SEARCH_KEYS contract are flagged as unknown", () => {
    // resId reaches Model.load via a different path (controller calls),
    // so it should surface as "unknown field" at this boundary.
    const issues = validateSearchParams({ resId: 7 });
    expect(issues.length).toBe(1);
    expect(issues[0]).toMatch(/unknown field 'resId'/);
});

test("unknown field is flagged with a remediation hint", () => {
    const issues = validateSearchParams({
        domain: [],
        somethingNew: "value", // not in the schema
    });
    expect(issues.length).toBe(1);
    expect(issues[0]).toMatch(/unknown field 'somethingNew'/);
    expect(issues[0]).toMatch(/SEARCH_PARAMS_SCHEMA/);
});

test("multiple unknown fields each surface as own issue", () => {
    const issues = validateSearchParams({
        domain: [],
        foo: 1,
        bar: 2,
    });
    // Two unknown fields → at least two issues (OWL may also raise its
    // own "extra-fields" error in addition; we only require ≥ 2).
    expect(issues.length).toBeGreaterThanOrEqual(2);
    const text = issues.join("\n");
    expect(text).toMatch(/foo/);
    expect(text).toMatch(/bar/);
});

test("schema enumerates exactly the SEARCH_KEYS contract", () => {
    // Pins the same four keys as core/constants.js:SEARCH_KEYS so a
    // one-sided update to either side gets caught here.
    expect(Object.keys(SEARCH_PARAMS_SCHEMA).toSorted()).toEqual([
        "context",
        "domain",
        "groupBy",
        "orderBy",
    ]);
});
