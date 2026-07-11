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

        // Mimic with_search's JSON round-trip through getGlobalState.
        const state = JSON.parse(JSON.stringify(exported));
        const target = {};
        execute(arrayToMap, state, target);

        const section = target.sections.get(1);
        const group = section.groups.get("g1");
        expect(group.values.get(10)).toBe(section.values.get(10));

        // The invariant is what makes toggles (filter.values) visible to
        // computeFilterDomain (group.values) without a refetch.
        section.values.get(10).checked = true;
        expect(group.values.get(10).checked).toBe(true);
    });
});
