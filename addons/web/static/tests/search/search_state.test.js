// @ts-check

/**
 * Pure unit tests for search/search_state.js state export/import.
 */

import { describe, expect, test } from "@odoo/hoot";
import { arrayToMap, execute, mapToArray } from "@web/search/search_state";

describe.current.tags("headless");

/** Build a minimal exportable source with a grouped filter section. */
function makeSource() {
    const value = { id: 10, checked: false, display_name: "Tag A" };
    const group = { id: "g1", name: "Group", values: new Map([[10, value]]) };
    const filter = {
        id: 1,
        type: "filter",
        values: new Map([[10, value]]),
        groups: new Map([["g1", group]]),
    };
    return {
        query: [{ searchItemId: 3 }],
        nextId: 4,
        nextGroupId: 2,
        nextGroupNumber: 2,
        orderByCount: false,
        searchItems: { 3: { id: 3, type: "filter" } },
        searchPanelInfo: { loaded: true, shouldReload: false },
        sections: new Map([[1, filter]]),
    };
}

describe("state export/import", () => {
    test("the export does not alias the live model", () => {
        const source = makeSource();
        const exported = {};
        execute(mapToArray, source, exported);

        source.query.push({ searchItemId: 99 });
        source.sections.get(1).values.get(10).checked = true;

        expect(exported.query).toEqual([{ searchItemId: 3 }]);
        const [, section] = exported.sections[0];
        const [, value] = section.values[0];
        expect(value.checked).toBe(false);
    });

    test("import re-aliases group values with filter values", () => {
        const source = makeSource();
        const exported = {};
        execute(mapToArray, source, exported);

        const state = JSON.parse(JSON.stringify(exported));
        const target = {};
        execute(arrayToMap, state, target);

        const section = target.sections.get(1);
        const group = section.groups.get("g1");
        expect(group.values.get(10)).toBe(section.values.get(10));

        section.values.get(10).checked = true;
        expect(group.values.get(10).checked).toBe(true);
    });

    test("import leaves the state object it was handed untouched", () => {
        const source = makeSource();
        const exported = {};
        execute(mapToArray, source, exported);
        const state = JSON.parse(JSON.stringify(exported));
        const before = JSON.parse(JSON.stringify(state));

        const target = {};
        execute(arrayToMap, state, target);

        // `execute` rewrites `values`/`groups` into Maps as it walks. Sharing
        // the value objects with the caller's state meant `load({ state })`
        // corrupted it in place — only WithSearch hid this, by always passing a
        // throwaway JSON.parse result.
        expect(state).toEqual(before);
        expect(Array.isArray(state.sections[0][1].values)).toBe(true);

        target.sections.get(1).values.get(10).checked = true;
        expect(state.sections[0][1].values[0][1].checked).toBe(false);
    });
});
