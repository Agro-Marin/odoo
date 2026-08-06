// @ts-check

/**
 * Pure unit tests for search/search_state.js state export/import.
 */

import { describe, expect, test } from "@odoo/hoot";
import {
    itemsFromState,
    itemsToState,
    panelFromState,
    panelToState,
    propertiesFromState,
    propertiesToState,
    queryFromState,
    queryToState,
} from "@web/search/search_state";

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
        searchViewFields: {},
    };
}

function exportSource(source) {
    return {
        ...queryToState(source),
        ...itemsToState(source),
        ...panelToState(source),
        ...propertiesToState(source),
    };
}

function importState(state, target = {}) {
    queryFromState(state, target);
    itemsFromState(state, target);
    panelFromState(state, target);
    propertiesFromState(state, target);
    return target;
}

describe("state export/import", () => {
    test("the export does not alias the live model", () => {
        const source = makeSource();
        const exported = exportSource(source);

        source.query.push({ searchItemId: 99 });
        source.sections.get(1).values.get(10).checked = true;

        expect(exported.query).toEqual([{ searchItemId: 3 }]);
        const [, section] = exported.sections[0];
        const [, value] = section.values[0];
        expect(value.checked).toBe(false);
    });

    test("import re-aliases group values with filter values", () => {
        const source = makeSource();
        const exported = exportSource(source);

        const state = JSON.parse(JSON.stringify(exported));
        const target = importState(state);

        const section = target.sections.get(1);
        const group = section.groups.get("g1");
        expect(group.values.get(10)).toBe(section.values.get(10));

        section.values.get(10).checked = true;
        expect(group.values.get(10).checked).toBe(true);
    });

    test("import leaves the state object it was handed untouched", () => {
        const source = makeSource();
        const exported = exportSource(source);
        const state = JSON.parse(JSON.stringify(exported));
        const before = JSON.parse(JSON.stringify(state));

        const target = importState(state);

        // The import rebuilds `values`/`groups` into Maps as it walks. Sharing
        // the value objects with the caller's state meant `load({ state })`
        // corrupted it in place — only WithSearch hid this, by always passing a
        // throwaway JSON.parse result.
        expect(state).toEqual(before);
        expect(Array.isArray(state.sections[0][1].values)).toBe(true);

        target.sections.get(1).values.get(10).checked = true;
        expect(state.sections[0][1].values[0][1].checked).toBe(false);
    });

    test("the export survives a JSON round-trip and imports identically", () => {
        const source = makeSource();
        const exported = exportSource(source);

        const direct = importState(exported);
        const roundTripped = importState(JSON.parse(JSON.stringify(exported)));

        expect(roundTripped.query).toEqual(direct.query);
        expect(roundTripped.searchItems).toEqual(direct.searchItems);
        expect([...roundTripped.sections.keys()]).toEqual([...direct.sections.keys()]);
    });
});

describe("panel concern", () => {
    test("searchDomain is exported and restored", () => {
        const source = makeSource();
        source.searchDomain = [["foo", "=", "a"]];

        const exported = panelToState(source);
        expect(exported.searchDomain).toEqual([["foo", "=", "a"]]);
        expect(exported.searchDomain).not.toBe(source.searchDomain);

        const target = {};
        panelFromState(JSON.parse(JSON.stringify(exported)), target);
        expect(target.searchDomain).toEqual([["foo", "=", "a"]]);
    });

    test("a source without a searchDomain exports none, and a legacy state restores none", () => {
        const source = makeSource();
        const exported = panelToState(source);
        expect("searchDomain" in exported).toBe(false);

        const target = {};
        panelFromState(exported, target);
        expect("searchDomain" in target).toBe(false);
    });
});

describe("properties concern", () => {
    function makePropertySource() {
        const parent = { name: "properties", type: "properties", string: "Properties" };
        return {
            searchViewFields: {
                properties: parent,
                "properties.my_char": {
                    name: "properties.my_char",
                    string: "My Char",
                    type: "char",
                    relatedPropertyField: parent,
                },
                foo: { name: "foo", type: "char", string: "Foo" },
            },
        };
    }

    test("only property-derived searchViewFields entries are exported", () => {
        const { propertySearchViewFields } = propertiesToState(makePropertySource());
        expect(Object.keys(propertySearchViewFields)).toEqual(["properties.my_char"]);
        expect(propertySearchViewFields["properties.my_char"].string).toBe("My Char");
    });

    test("import merges the entries and re-aliases the parent field", () => {
        const state = JSON.parse(
            JSON.stringify(propertiesToState(makePropertySource())),
        );
        const liveParent = {
            name: "properties",
            type: "properties",
            string: "Properties",
        };
        const target = { searchViewFields: { properties: liveParent } };

        propertiesFromState(state, target);

        const restored = target.searchViewFields["properties.my_char"];
        expect(restored.string).toBe("My Char");
        expect(restored.relatedPropertyField).toBe(liveParent);
    });

    test("import never overwrites a live entry, and tolerates legacy states", () => {
        const live = { name: "properties.my_char", string: "Fresh", type: "char" };
        const target = { searchViewFields: { "properties.my_char": live } };
        propertiesFromState(
            {
                propertySearchViewFields: {
                    "properties.my_char": {
                        name: "properties.my_char",
                        string: "Stale",
                    },
                },
            },
            target,
        );
        expect(target.searchViewFields["properties.my_char"]).toBe(live);

        // Legacy state: no propertySearchViewFields key at all.
        propertiesFromState({}, target);
        expect(target.searchViewFields["properties.my_char"]).toBe(live);
    });
});
