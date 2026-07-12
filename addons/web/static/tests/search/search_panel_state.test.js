// @ts-check

/**
 * Pure unit tests for search/search_panel/search_panel_state.js.
 *
 * Each exported function receives a SearchModel as its first argument
 * (delegation pattern). Tests build a minimal plain-object mock — no OWL,
 * no DOM fixtures, no server calls.
 *
 * fetchCategories, fetchFilters, fetchSections, reloadSections are not tested
 * here: they involve live ORM calls and multi-step async orchestration covered
 * by existing search_panel integration tests.
 */

import { describe, expect, test } from "@odoo/hoot";
import {
    clearSections,
    createCategoryTree,
    createFilterTree,
    ensureCategoryValue,
    fetchCategories,
    getSections,
    shouldWaitForData,
    toggleCategoryValue,
    toggleFilterValues,
} from "@web/search/search_panel/search_panel_state";
import { hasValues } from "@web/search/search_state";

// Helpers

/**
 * Build a minimal SearchModel mock for search panel state functions.
 * @param {Map<number,Object>} sections
 * @param {Object} [overrides]
 */
function makeSearchModel(sections, overrides = {}) {
    const notifications = [];
    const model = {
        sections,
        categories: [],
        filters: [],
        searchDomain: [],
        _notify() {
            notifications.push("notify");
        },
        _ensureCategoryValue(cat, ids) {
            ensureCategoryValue(cat, ids);
        },
        _notifications: notifications,
        ...overrides,
    };
    return model;
}

/** Build a category section object. */
function makeCategory(id, overrides = {}) {
    return {
        id,
        type: "category",
        activeValueId: false,
        values: new Map(),
        index: id,
        expand: false,
        enableCounters: false,
        ...overrides,
    };
}

/** Build a filter section object. */
function makeFilter(id, valueEntries = [], overrides = {}) {
    const values = new Map(
        valueEntries.map(([vid, checked]) => [vid, { id: vid, checked }]),
    );
    return {
        id,
        type: "filter",
        values,
        index: id,
        domain: "[]",
        expand: false,
        enableCounters: false,
        ...overrides,
    };
}

// toggleCategoryValue

describe("toggleCategoryValue", () => {
    test("sets activeValueId on the category", () => {
        const cat = makeCategory(1, { activeValueId: false });
        const sections = new Map([[1, cat]]);
        const model = makeSearchModel(sections);

        toggleCategoryValue(model, 1, 42);

        expect(cat.activeValueId).toBe(42);
    });

    test("replaces an existing activeValueId", () => {
        const cat = makeCategory(1, { activeValueId: 10 });
        const sections = new Map([[1, cat]]);
        const model = makeSearchModel(sections);

        toggleCategoryValue(model, 1, 20);

        expect(cat.activeValueId).toBe(20);
    });

    test("calls _notify", () => {
        const sections = new Map([[1, makeCategory(1)]]);
        const model = makeSearchModel(sections);

        toggleCategoryValue(model, 1, 5);

        expect(model._notifications.length).toBe(1);
    });
});

// toggleFilterValues

describe("toggleFilterValues", () => {
    test("toggles checked state of given value IDs", () => {
        const filter = makeFilter(1, [
            [10, false],
            [20, true],
        ]);
        const sections = new Map([[1, filter]]);
        const model = makeSearchModel(sections);

        toggleFilterValues(model, 1, [10, 20]);

        expect(filter.values.get(10).checked).toBe(true);
        expect(filter.values.get(20).checked).toBe(false);
    });

    test("forceTo=true sets all values to checked", () => {
        const filter = makeFilter(1, [
            [1, false],
            [2, false],
            [3, true],
        ]);
        const sections = new Map([[1, filter]]);
        const model = makeSearchModel(sections);

        toggleFilterValues(model, 1, [1, 2, 3], true);

        expect(filter.values.get(1).checked).toBe(true);
        expect(filter.values.get(2).checked).toBe(true);
        expect(filter.values.get(3).checked).toBe(true);
    });

    test("forceTo=false clears all values", () => {
        const filter = makeFilter(1, [
            [1, true],
            [2, true],
        ]);
        const sections = new Map([[1, filter]]);
        const model = makeSearchModel(sections);

        toggleFilterValues(model, 1, [1, 2], false);

        expect(filter.values.get(1).checked).toBe(false);
        expect(filter.values.get(2).checked).toBe(false);
    });

    test("calls _notify", () => {
        const filter = makeFilter(1, [[1, false]]);
        const sections = new Map([[1, filter]]);
        const model = makeSearchModel(sections);

        toggleFilterValues(model, 1, [1]);

        expect(model._notifications.length).toBe(1);
    });

    test("ignores ids that no longer exist (refetch between render and click)", () => {
        const filter = makeFilter(1, [[10, false]]);
        const sections = new Map([[1, filter]]);
        const model = makeSearchModel(sections);

        // Value 20 was rendered but a counter refetch rebuilt `values`
        // without it: the click must not throw and 10 still toggles.
        toggleFilterValues(model, 1, [10, 20]);

        expect(filter.values.get(10).checked).toBe(true);
        expect(filter.values.has(20)).toBe(false);
        expect(model._notifications.length).toBe(1);
    });
});

// clearSections

describe("clearSections", () => {
    test("resets category activeValueId to false", () => {
        const cat = makeCategory(1, { activeValueId: 7 });
        const sections = new Map([[1, cat]]);
        const model = makeSearchModel(sections);

        clearSections(model, [1]);

        expect(cat.activeValueId).toBe(false);
    });

    test("unchecks all filter values", () => {
        const filter = makeFilter(2, [
            [10, true],
            [20, true],
        ]);
        const sections = new Map([[2, filter]]);
        const model = makeSearchModel(sections);

        clearSections(model, [2]);

        expect(filter.values.get(10).checked).toBe(false);
        expect(filter.values.get(20).checked).toBe(false);
    });

    test("clears multiple sections in one call", () => {
        const cat = makeCategory(1, { activeValueId: 5 });
        const filter = makeFilter(2, [[1, true]]);
        const sections = new Map([
            [1, cat],
            [2, filter],
        ]);
        const model = makeSearchModel(sections);

        clearSections(model, [1, 2]);

        expect(cat.activeValueId).toBe(false);
        expect(filter.values.get(1).checked).toBe(false);
    });
});

// getSections

describe("getSections", () => {
    test("returns sections in Map insertion order (arch order)", () => {
        const sections = new Map([
            [3, makeCategory(3)],
            [1, makeCategory(1)],
            [2, makeCategory(2)],
        ]);
        const model = makeSearchModel(sections);

        const result = getSections(model);

        expect(result.map((s) => s.id)).toEqual([3, 1, 2]);
    });

    test("marks category as empty when values.size <= 1", () => {
        // Only 1 value (the 'false' root) → considered empty
        const cat = makeCategory(1);
        cat.values.set(false, { id: false });
        const sections = new Map([[1, cat]]);
        const model = makeSearchModel(sections);

        const result = getSections(model);

        expect(result[0].empty).toBe(true);
    });

    test("marks filter as empty when values.size is 0", () => {
        const filter = makeFilter(1, []); // no values
        const sections = new Map([[1, filter]]);
        const model = makeSearchModel(sections);

        const result = getSections(model);

        expect(result[0].empty).toBe(true);
    });

    test("marks filter as non-empty when it has values", () => {
        const filter = makeFilter(1, [[1, false]]);
        const sections = new Map([[1, filter]]);
        const model = makeSearchModel(sections);

        const result = getSections(model);

        expect(result[0].empty).toBe(false);
    });

    test("applies predicate filter", () => {
        const sections = new Map([
            [1, makeCategory(1)],
            [2, makeFilter(2)],
        ]);
        const model = makeSearchModel(sections);

        const result = getSections(model, (s) => s.type === "filter");

        expect(result.length).toBe(1);
        expect(result[0].type).toBe("filter");
    });

    test("returns shallow copies — mutations do not affect originals", () => {
        const cat = makeCategory(1, { activeValueId: false });
        const sections = new Map([[1, cat]]);
        const model = makeSearchModel(sections);

        const result = getSections(model);
        result[0].activeValueId = 999; // mutate the copy

        // Original is unchanged
        expect(cat.activeValueId).toBe(false);
    });

    test("memoizes the list until a tree rebuild invalidates it", () => {
        const cat = makeCategory(1, { hierarchize: false });
        cat.values.set(false, { id: false, childrenIds: [], parentId: false });
        const sections = new Map([[1, cat]]);
        const model = makeSearchModel(sections);

        const first = getSections(model);
        expect(getSections(model)).toBe(first);
        expect(first[0].empty).toBe(true);

        createCategoryTree(model, 1, {
            parent_field: "parent_id",
            values: [{ id: 10, parent_id: false }],
        });

        const second = getSections(model);
        expect(second).not.toBe(first);
        expect(second[0].empty).toBe(false);
    });
});

// ensureCategoryValue

describe("ensureCategoryValue", () => {
    test("keeps activeValueId when it is in valueIds", () => {
        const cat = makeCategory(1, { activeValueId: 5 });

        ensureCategoryValue(cat, [false, 5, 10]);

        expect(cat.activeValueId).toBe(5);
    });

    test("resets activeValueId to first valueId when current is absent", () => {
        const cat = makeCategory(1, { activeValueId: 99 });

        ensureCategoryValue(cat, [false, 5, 10]);

        expect(cat.activeValueId).toBe(false); // first element
    });

    test("resets to false when valueIds contains only [false]", () => {
        const cat = makeCategory(1, { activeValueId: 7 });

        ensureCategoryValue(cat, [false]);

        expect(cat.activeValueId).toBe(false);
    });
});

// createCategoryTree

describe("createCategoryTree", () => {
    test("populates values Map from server result", () => {
        const cat = makeCategory(1, { hierarchize: false });
        const sections = new Map([[1, cat]]);
        const model = makeSearchModel(sections);

        createCategoryTree(model, 1, {
            parent_field: "parent_id",
            values: [
                { id: 10, display_name: "Apple", parent_id: false },
                { id: 20, display_name: "Banana", parent_id: false },
            ],
        });

        expect(cat.values.has(10)).toBe(true);
        expect(cat.values.has(20)).toBe(true);
    });

    test("builds correct rootIds list (false + top-level ids)", () => {
        const cat = makeCategory(1, { hierarchize: false });
        const sections = new Map([[1, cat]]);
        const model = makeSearchModel(sections);

        createCategoryTree(model, 1, {
            parent_field: "parent_id",
            values: [
                { id: 10, parent_id: false },
                { id: 20, parent_id: false },
                { id: 30, parent_id: 10 }, // child of 10
            ],
        });

        // rootIds should be [false, 10, 20] — only top-level parents
        expect(cat.rootIds).toEqual([false, 10, 20]);
    });

    test("sets childrenIds on parent values", () => {
        const cat = makeCategory(1, { hierarchize: true });
        const sections = new Map([[1, cat]]);
        const model = makeSearchModel(sections);

        createCategoryTree(model, 1, {
            parent_field: "parent_id",
            values: [
                { id: 10, parent_id: false },
                { id: 20, parent_id: 10 },
            ],
        });

        expect(cat.values.get(10).childrenIds).toInclude(20);
    });

    test("sets errorMsg and empty values on server error", () => {
        const cat = makeCategory(1, { hierarchize: false });
        const sections = new Map([[1, cat]]);
        const model = makeSearchModel(sections);

        createCategoryTree(model, 1, {
            parent_field: "parent_id",
            values: [],
            error_msg: "Access denied",
        });

        expect(cat.errorMsg).toBe("Access denied");
        expect(cat.values.size).toBe(0);
    });

    test("recovers from a failed fetch: a successful rebuild clears errorMsg", () => {
        const cat = makeCategory(1, { hierarchize: false });
        cat.values.set(false, { id: false, childrenIds: [], parentId: false });
        const sections = new Map([[1, cat]]);
        const model = makeSearchModel(sections);

        // First fetch fails (server-side error or stamped by the client-side
        // catch in fetchCategories): the section becomes an error tile.
        createCategoryTree(model, 1, { values: [], error_msg: "Network error" });
        expect(cat.errorMsg).toBe("Network error");
        expect(hasValues(cat)).toBe(true); // error tile rendered

        // A later refetch succeeds: the section must render its values again.
        createCategoryTree(model, 1, {
            parent_field: "parent_id",
            values: [{ id: 10, parent_id: false }],
        });

        expect("errorMsg" in cat).toBe(false);
        expect(cat.values.has(10)).toBe(true);
        expect(hasValues(cat)).toBe(true); // now from actual values
    });

    test("drops values removed server-side on a subsequent fetch", () => {
        const cat = makeCategory(1, { hierarchize: false });
        // Seed the synthetic "All" root as the arch parser does.
        cat.values.set(false, { id: false, childrenIds: [], parentId: false });
        const sections = new Map([[1, cat]]);
        const model = makeSearchModel(sections);

        // First fetch returns two values.
        createCategoryTree(model, 1, {
            parent_field: "parent_id",
            values: [
                { id: 10, parent_id: false },
                { id: 20, parent_id: false },
            ],
        });
        expect(cat.values.has(10)).toBe(true);
        expect(cat.values.has(20)).toBe(true);

        // A narrower domain reload no longer returns value 20.
        createCategoryTree(model, 1, {
            parent_field: "parent_id",
            values: [{ id: 10, parent_id: false }],
        });

        expect(cat.values.has(20)).toBe(false); // removed server-side → gone
        expect(cat.values.has(10)).toBe(true);
        expect(cat.values.has(false)).toBe(true); // "All" root preserved
        expect(cat.rootIds).toEqual([false, 10]);
    });
});

// createFilterTree

describe("createFilterTree", () => {
    test("populates values from flat server result", () => {
        const filter = makeFilter(1);
        const sections = new Map([[1, filter]]);
        const model = makeSearchModel(sections);

        createFilterTree(model, 1, {
            values: [
                { id: 10, display_name: "Tag A" },
                { id: 20, display_name: "Tag B" },
            ],
        });

        expect(filter.values.has(10)).toBe(true);
        expect(filter.values.has(20)).toBe(true);
    });

    test("restores checked state for values that were previously checked", () => {
        const filter = makeFilter(1, [[10, true]]); // value 10 was checked
        const sections = new Map([[1, filter]]);
        const model = makeSearchModel(sections);

        createFilterTree(model, 1, {
            values: [
                { id: 10, display_name: "Tag A" },
                { id: 20, display_name: "Tag B" },
            ],
        });

        expect(filter.values.get(10).checked).toBe(true);
        expect(filter.values.get(20).checked).toBe(false);
    });

    test("sets errorMsg on server error", () => {
        const filter = makeFilter(1);
        const sections = new Map([[1, filter]]);
        const model = makeSearchModel(sections);

        createFilterTree(model, 1, {
            values: [],
            error_msg: "Server error",
        });

        expect(filter.errorMsg).toBe("Server error");
    });

    test("recovers from a failed fetch: a successful rebuild clears errorMsg", () => {
        const filter = makeFilter(1);
        const sections = new Map([[1, filter]]);
        const model = makeSearchModel(sections);

        createFilterTree(model, 1, { values: [], error_msg: "Network error" });
        expect(filter.errorMsg).toBe("Network error");
        expect(hasValues(filter)).toBe(true); // error tile rendered

        createFilterTree(model, 1, {
            values: [{ id: 10, display_name: "Tag A" }],
        });

        expect("errorMsg" in filter).toBe(false);
        expect(filter.values.has(10)).toBe(true);
        expect(hasValues(filter)).toBe(true); // now from actual values
    });
});

// fetchCategories — per-section load id

describe("fetchCategories per-section stale guard", () => {
    /** A resolvable promise. */
    function makeDeferred() {
        let resolve;
        const promise = new Promise((r) => {
            resolve = r;
        });
        return { promise, resolve };
    }

    /**
     * Build a mock orm whose `.cache(opts).call(...)` returns a deferred keyed
     * by the requested field name; the test resolves each call by hand.
     */
    function makeMockOrm() {
        const deferredsByField = new Map();
        const orm = {
            cache() {
                return this;
            },
            call(_resModel, _method, args) {
                const fieldName = args[0];
                const list = deferredsByField.get(fieldName) || [];
                const deferred = makeDeferred();
                list.push(deferred);
                deferredsByField.set(fieldName, list);
                return deferred.promise;
            },
        };
        return { orm, deferredsByField };
    }

    test("a later fetch of one section does not drop another section's in-flight response", async () => {
        const catA = makeCategory(1, { fieldName: "a" });
        const catB = makeCategory(2, { fieldName: "b" });
        const sections = new Map([
            [1, catA],
            [2, catB],
        ]);
        const created = [];
        const { orm, deferredsByField } = makeMockOrm();
        const model = makeSearchModel(sections, {
            _sectionLoadIds: new Map(),
            orm,
            globalContext: {},
            resModel: "res.partner",
            searchDomain: [],
            categories: [catA, catB],
            _getFilterDomain: () => [],
            _getCategoryDomain: () => [],
            _createCategoryTree: (id, result) => created.push([id, result]),
            _reset() {},
            trigger() {},
        });

        // First fetch of BOTH sections (their in-flight responses are pending).
        const p1 = fetchCategories(model, [catA, catB]);
        // A later fetch of ONLY section B (e.g. a counter-only reload) bumps
        // just B's load id — A's in-flight fetch must survive.
        const p2 = fetchCategories(model, [catB]);

        const resultA = { values: [{ id: 10 }], _tag: "A" };
        const resultB1 = { values: [{ id: 20 }], _tag: "B1" };
        const resultB2 = { values: [{ id: 30 }], _tag: "B2" };
        deferredsByField.get("a")[0].resolve(resultA);
        deferredsByField.get("b")[0].resolve(resultB1); // stale (load id 1)
        deferredsByField.get("b")[1].resolve(resultB2); // current (load id 2)
        await Promise.all([p1, p2]);

        // Exactly two applications: section A's only fetch, and section B's
        // newest fetch. The superseded B response (resultB1) was discarded, and
        // — the actual regression — section A's response was NOT dropped by B's
        // later fetch (a model-wide load id used to discard it).
        expect(created.length).toBe(2);
        const applied = new Map(created);
        expect(applied.get(1)).toBe(resultA);
        expect(applied.get(2)).toBe(resultB2);
    });
});

// shouldWaitForData

describe("shouldWaitForData", () => {
    test("returns true when categories exist AND any filter has non-empty domain", () => {
        const sections = new Map();
        const model = makeSearchModel(sections, {
            categories: [{ fieldName: "categ_id", activeValueId: false }],
            filters: [{ domain: "['active','=',true]", enableCounters: false }],
            searchDomain: [],
        });

        expect(shouldWaitForData(model, false)).toBe(true);
    });

    test("returns false when searchDomain is empty (no category+filter combo)", () => {
        const sections = new Map();
        const model = makeSearchModel(sections, {
            categories: [],
            filters: [],
            searchDomain: [],
        });

        expect(shouldWaitForData(model, true)).toBe(false);
    });

    test("returns true when searchDomain non-empty and a non-expand section exists", () => {
        const section = makeFilter(1, [], { expand: false });
        const sections = new Map([[1, section]]);
        const model = makeSearchModel(sections, {
            categories: [],
            filters: [],
            searchDomain: [["active", "=", true]],
        });

        expect(shouldWaitForData(model, true)).toBe(true);
    });

    test("returns false when all sections have expand=true", () => {
        const section = makeFilter(1, [], { expand: true });
        const sections = new Map([[1, section]]);
        const model = makeSearchModel(sections, {
            categories: [],
            filters: [],
            searchDomain: [["active", "=", true]],
        });

        expect(shouldWaitForData(model, true)).toBe(false);
    });

    test("returns false when searchDomainChanged is false even with non-expand sections", () => {
        const section = makeFilter(1, [], { expand: false });
        const sections = new Map([[1, section]]);
        const model = makeSearchModel(sections, {
            categories: [],
            filters: [],
            searchDomain: [["active", "=", true]],
        });

        // searchDomainChanged = false → section.expand is irrelevant
        expect(shouldWaitForData(model, false)).toBe(false);
    });
});
