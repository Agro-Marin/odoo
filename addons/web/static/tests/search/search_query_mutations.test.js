// @ts-check

/**
 * Pure unit tests for search/search_query_mutations.js.
 *
 * Each exported function receives a SearchModel as its first argument
 * (delegation pattern). Tests build a minimal plain-object mock instead of
 * mounting a full OWL component tree. The mock wires delegation methods back
 * to the real exported functions so the full call chain is exercised.
 *
 * spawnCustomFilterDialog and createIrFilters are not tested here:
 * the former requires a dialog service; the latter requires a live ORM call
 * and rpcBus side effects — both are covered by existing integration tests.
 */

import { describe, expect, test } from "@odoo/hoot";
import {
    addAutoCompletionValues,
    clearFilters,
    clearQuery,
    createNewFilters,
    createNewFavorite,
    createNewGroupBy,
    deactivateGroup,
    switchGroupBySort,
    toggleDateFilter,
    toggleDateGroupBy,
    toggleSearchItem,
} from "@web/search/search_query_mutations";
import { FAVORITE_PRIVATE_GROUP, FAVORITE_SHARED_GROUP, SPECIAL } from "@web/search/search_state";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Build a minimal SearchModel mock.
 *
 * Delegation methods (`deactivateGroup`, `clearQuery`, etc.) are wired to the
 * real exported functions so that compound operations (e.g. clearFilters calling
 * deactivateGroup, createNewFavorite calling clearQuery) exercise the full chain.
 *
 * @param {Object} [overrides]
 * @returns {Object}
 */
function makeSearchModel(overrides = {}) {
    const notifications = [];
    const model = {
        query: [],
        searchItems: {},
        orderByCount: false,
        blockNotification: false,
        nextId: 1,
        nextGroupId: 1,
        nextGroupNumber: 1,
        searchViewFields: {},
        facets: [],

        _notify() {
            notifications.push("notify");
        },
        deactivateGroup(groupId) {
            deactivateGroup(this, groupId);
        },
        clearQuery() {
            clearQuery(this);
        },
        toggleDateGroupBy(id, intervalId) {
            toggleDateGroupBy(this, id, intervalId);
        },
        toggleSearchItem(id) {
            toggleSearchItem(this, id);
        },
        /** Derive selected generatorIds live from query so tests stay realistic. */
        _getSelectedGeneratorIds(searchItemId) {
            return this.query
                .filter((q) => q.searchItemId === searchItemId && "generatorId" in q)
                .map((q) => q.generatorId);
        },
        /** Stub: returns a serverSideId without a real ORM call. */
        _createIrFilters: async () => 42,
        /** Stub: always returns a private-user preFavorite. */
        _getIrFilterDescription: () => ({
            preFavorite: { userIds: [1], domain: "[]", context: {}, orderedBy: [] },
            irFilter: { name: "My Fav", domain: "[]", context: {} },
        }),

        _notifications: notifications,
        ...overrides,
    };
    return model;
}

/**
 * Add a search item and (optionally) activate it in the query.
 * @param {Object} model
 * @param {number} id
 * @param {Object} item - partial search item (type, groupId required)
 * @param {boolean} [activate]
 */
function addItem(model, id, item, activate = false) {
    model.searchItems[id] = { id, groupId: id, groupNumber: 1, ...item };
    if (activate) {
        model.query.push({ searchItemId: id });
    }
}

// ---------------------------------------------------------------------------
// addAutoCompletionValues
// ---------------------------------------------------------------------------

describe("addAutoCompletionValues", () => {
    test("adds a new autocomplete value to query", () => {
        const model = makeSearchModel();
        addItem(model, 1, { type: "field" });

        addAutoCompletionValues(model, 1, { label: "Alice", value: "Alice", operator: "=" });

        expect(model.query.length).toBe(1);
        expect(model.query[0].autocompleteValue).toEqual({
            label: "Alice",
            value: "Alice",
            operator: "=",
        });
    });

    test("updates label when same value+operator already active", () => {
        const model = makeSearchModel();
        addItem(model, 1, { type: "field" });
        model.query.push({ searchItemId: 1, autocompleteValue: { label: "Old", value: "Alice", operator: "=" } });

        addAutoCompletionValues(model, 1, { label: "New", value: "Alice", operator: "=" });

        // no duplicate added
        expect(model.query.length).toBe(1);
        expect(model.query[0].autocompleteValue.label).toBe("New");
    });

    test("ignores non-field search items", () => {
        const model = makeSearchModel();
        addItem(model, 1, { type: "filter" });

        addAutoCompletionValues(model, 1, { label: "X", value: "X", operator: "=" });

        expect(model.query.length).toBe(0);
    });

    test("calls _notify", () => {
        const model = makeSearchModel();
        addItem(model, 1, { type: "field" });

        addAutoCompletionValues(model, 1, { label: "A", value: "A", operator: "=" });

        expect(model._notifications.length).toBeGreaterThan(0);
    });
});

// ---------------------------------------------------------------------------
// clearQuery
// ---------------------------------------------------------------------------

describe("clearQuery", () => {
    test("empties the query array", () => {
        const model = makeSearchModel();
        model.query = [{ searchItemId: 1 }, { searchItemId: 2 }];

        clearQuery(model);

        expect(model.query.length).toBe(0);
    });

    test("resets orderByCount to false", () => {
        const model = makeSearchModel({ orderByCount: "Desc" });

        clearQuery(model);

        expect(model.orderByCount).toBe(false);
    });
});

// ---------------------------------------------------------------------------
// clearFilters
// ---------------------------------------------------------------------------

describe("clearFilters", () => {
    test("removes non-groupBy facets from query", () => {
        const model = makeSearchModel();
        addItem(model, 1, { type: "filter", groupId: 1 }, true);
        addItem(model, 2, { type: "groupBy", groupId: 2 }, true);
        model.facets = [
            { type: "filter", groupId: 1 },
            { type: "groupBy", groupId: 2 },
        ];

        clearFilters(model);

        // groupBy (id=2) must remain; filter (id=1) must be gone
        expect(model.query.some((q) => q.searchItemId === 2)).toBe(true);
        expect(model.query.some((q) => q.searchItemId === 1)).toBe(false);
    });

    test("leaves groupBy facets untouched", () => {
        const model = makeSearchModel();
        addItem(model, 10, { type: "groupBy", groupId: 10 }, true);
        model.facets = [{ type: "groupBy", groupId: 10 }];

        clearFilters(model);

        expect(model.query.length).toBe(1);
        expect(model.query[0].searchItemId).toBe(10);
    });
});

// ---------------------------------------------------------------------------
// deactivateGroup
// ---------------------------------------------------------------------------

describe("deactivateGroup", () => {
    test("removes all query elements with matching groupId", () => {
        const model = makeSearchModel();
        addItem(model, 1, { type: "filter", groupId: 5 }, true);
        addItem(model, 2, { type: "filter", groupId: 5 }, true);
        addItem(model, 3, { type: "filter", groupId: 6 }, true);

        deactivateGroup(model, 5);

        expect(model.query.length).toBe(1);
        expect(model.query[0].searchItemId).toBe(3);
    });

    test("SPECIAL groupId removes defaultGroupBy property", () => {
        const model = makeSearchModel();
        model.defaultGroupBy = ["name"];

        deactivateGroup(model, SPECIAL);

        expect("defaultGroupBy" in model).toBe(false);
    });

    test("no-op when groupId not present in query", () => {
        const model = makeSearchModel();
        addItem(model, 1, { type: "filter", groupId: 1 }, true);

        deactivateGroup(model, 99);

        expect(model.query.length).toBe(1);
    });
});

// ---------------------------------------------------------------------------
// toggleSearchItem
// ---------------------------------------------------------------------------

describe("toggleSearchItem", () => {
    test("activates an inactive filter", () => {
        const model = makeSearchModel();
        addItem(model, 1, { type: "filter", groupId: 1 });

        toggleSearchItem(model, 1);

        expect(model.query.some((q) => q.searchItemId === 1)).toBe(true);
    });

    test("deactivates an active filter", () => {
        const model = makeSearchModel();
        addItem(model, 1, { type: "filter", groupId: 1 }, true);

        toggleSearchItem(model, 1);

        expect(model.query.some((q) => q.searchItemId === 1)).toBe(false);
    });

    test("activating a favorite clears the query first", () => {
        const model = makeSearchModel();
        addItem(model, 1, { type: "filter", groupId: 1 }, true);
        addItem(model, 2, { type: "favorite", groupId: 2 });

        toggleSearchItem(model, 2);

        // Only the favorite is active; the filter was cleared
        expect(model.query.length).toBe(1);
        expect(model.query[0].searchItemId).toBe(2);
    });

    test("ignores dateFilter type items", () => {
        const model = makeSearchModel();
        addItem(model, 1, { type: "dateFilter", groupId: 1 });

        toggleSearchItem(model, 1);

        // dateFilter is silently ignored
        expect(model.query.length).toBe(0);
    });
});

// ---------------------------------------------------------------------------
// toggleDateGroupBy
// ---------------------------------------------------------------------------

describe("toggleDateGroupBy", () => {
    test("adds intervalId entry to query when not present", () => {
        const model = makeSearchModel();
        addItem(model, 1, { type: "dateGroupBy", defaultIntervalId: "month" });

        toggleDateGroupBy(model, 1, "month");

        expect(model.query).toEqual([{ searchItemId: 1, intervalId: "month" }]);
    });

    test("uses defaultIntervalId when intervalId not given", () => {
        const model = makeSearchModel();
        addItem(model, 1, { type: "dateGroupBy", defaultIntervalId: "week" });

        toggleDateGroupBy(model, 1);

        expect(model.query[0].intervalId).toBe("week");
    });

    test("removes intervalId entry when already active", () => {
        const model = makeSearchModel();
        addItem(model, 1, { type: "dateGroupBy", defaultIntervalId: "month" });
        model.query.push({ searchItemId: 1, intervalId: "month" });

        toggleDateGroupBy(model, 1, "month");

        expect(model.query.length).toBe(0);
    });

    test("ignores non-dateGroupBy items", () => {
        const model = makeSearchModel();
        addItem(model, 1, { type: "groupBy", defaultIntervalId: "month" });

        toggleDateGroupBy(model, 1, "month");

        expect(model.query.length).toBe(0);
    });
});

// ---------------------------------------------------------------------------
// toggleDateFilter
// ---------------------------------------------------------------------------

describe("toggleDateFilter", () => {
    test("custom generatorId: replaces any existing entries for the item", () => {
        const model = makeSearchModel();
        addItem(model, 1, { type: "dateFilter" });
        // pre-populate another entry for the same item
        model.query.push({ searchItemId: 1, generatorId: "custom_old" });

        toggleDateFilter(model, 1, "custom_2024_01_01");

        expect(model.query.length).toBe(1);
        expect(model.query[0].generatorId).toBe("custom_2024_01_01");
    });

    test("removes an existing generatorId entry (year stays, no cascade remove)", () => {
        const model = makeSearchModel();
        addItem(model, 1, { type: "dateFilter" });
        model.query = [
            { searchItemId: 1, generatorId: "year" },
            { searchItemId: 1, generatorId: "third_quarter" },
        ];

        // Deactivate third_quarter — year remains so no cascade clear
        toggleDateFilter(model, 1, "third_quarter");

        expect(model.query.some((q) => q.generatorId === "year")).toBe(true);
        expect(model.query.some((q) => q.generatorId === "third_quarter")).toBe(false);
    });

    test("removing last year entry clears all remaining entries for that item", () => {
        const model = makeSearchModel();
        addItem(model, 1, { type: "dateFilter" });
        model.query = [{ searchItemId: 1, generatorId: "year" }];

        toggleDateFilter(model, 1, "year");

        expect(model.query.filter((q) => q.searchItemId === 1).length).toBe(0);
    });

    test("non-custom add: adds generatorId; with year already present no auto-year", () => {
        const model = makeSearchModel();
        addItem(model, 1, { type: "dateFilter" });
        // Pre-seed a year so yearSelected() returns true → getPeriodOptions not called
        model.query = [{ searchItemId: 1, generatorId: "year" }];

        toggleDateFilter(model, 1, "third_quarter");

        const generatorIds = model.query
            .filter((q) => q.searchItemId === 1)
            .map((q) => q.generatorId);
        expect(generatorIds).toInclude("third_quarter");
        expect(generatorIds).toInclude("year");
    });

    test("ignores non-dateFilter items", () => {
        const model = makeSearchModel();
        addItem(model, 1, { type: "filter" });

        toggleDateFilter(model, 1, "year");

        expect(model.query.length).toBe(0);
    });
});

// ---------------------------------------------------------------------------
// switchGroupBySort
// ---------------------------------------------------------------------------

describe("switchGroupBySort", () => {
    test("starts at false, first switch → Desc", () => {
        const model = makeSearchModel({ orderByCount: false });

        switchGroupBySort(model);

        expect(model.orderByCount).toBe("Desc");
    });

    test("Desc → Asc", () => {
        const model = makeSearchModel({ orderByCount: "Desc" });

        switchGroupBySort(model);

        expect(model.orderByCount).toBe("Asc");
    });

    test("Asc → Desc", () => {
        const model = makeSearchModel({ orderByCount: "Asc" });

        switchGroupBySort(model);

        expect(model.orderByCount).toBe("Desc");
    });
});

// ---------------------------------------------------------------------------
// createNewFilters
// ---------------------------------------------------------------------------

describe("createNewFilters", () => {
    test("creates filter items and activates them in query", () => {
        const model = makeSearchModel();
        const prefilters = [
            { description: "Active", domain: "[['active','=',true]]" },
            { description: "Draft", domain: "[['state','=','draft']]" },
        ];

        createNewFilters(model, prefilters);

        expect(Object.keys(model.searchItems).length).toBe(2);
        expect(model.query.length).toBe(2);
        expect(model.searchItems[1].type).toBe("filter");
        expect(model.searchItems[2].type).toBe("filter");
    });

    test("assigns sequential IDs starting from nextId", () => {
        const model = makeSearchModel({ nextId: 5 });

        createNewFilters(model, [{ description: "X", domain: "[]" }]);

        expect(5 in model.searchItems).toBe(true);
        expect(model.nextId).toBe(6);
    });

    test("returns undefined for empty prefilters and does not call _notify", () => {
        const model = makeSearchModel();

        createNewFilters(model, []);

        expect(model.query.length).toBe(0);
        expect(model._notifications.length).toBe(0);
    });

    test("all filters share the same groupId and groupNumber", () => {
        const model = makeSearchModel();

        createNewFilters(model, [
            { description: "A", domain: "[]" },
            { description: "B", domain: "[]" },
        ]);

        expect(model.searchItems[1].groupId).toBe(model.searchItems[2].groupId);
        expect(model.searchItems[1].groupNumber).toBe(model.searchItems[2].groupNumber);
    });
});

// ---------------------------------------------------------------------------
// createNewGroupBy
// ---------------------------------------------------------------------------

describe("createNewGroupBy", () => {
    test("non-date field: creates groupBy item and activates it", () => {
        const model = makeSearchModel();
        model.searchViewFields = { partner_id: { string: "Partner", type: "many2one" } };

        createNewGroupBy(model, "partner_id");

        const item = model.searchItems[1];
        expect(item.type).toBe("groupBy");
        expect(item.fieldName).toBe("partner_id");
        expect(model.query.some((q) => q.searchItemId === 1)).toBe(true);
    });

    test("date field: creates dateGroupBy item with default interval", () => {
        const model = makeSearchModel();
        model.searchViewFields = { order_date: { string: "Order Date", type: "date" } };

        createNewGroupBy(model, "order_date");

        const item = model.searchItems[1];
        expect(item.type).toBe("dateGroupBy");
        expect(item.defaultIntervalId).toBe("month"); // DEFAULT_INTERVAL
    });

    test("uses existing groupBy's groupId when one exists", () => {
        const model = makeSearchModel({ nextGroupId: 3 });
        model.searchViewFields = { name: { string: "Name", type: "char" } };
        // Pre-existing groupBy item with groupId = 7
        model.searchItems[99] = { type: "groupBy", groupId: 7 };

        createNewGroupBy(model, "name");

        // New item should reuse groupId 7, NOT allocate nextGroupId
        expect(model.searchItems[1].groupId).toBe(7);
        // nextGroupId should NOT have been consumed
        expect(model.nextGroupId).toBe(3);
    });

    test("custom flag is set on new item", () => {
        const model = makeSearchModel();
        model.searchViewFields = { name: { string: "Name", type: "char" } };

        createNewGroupBy(model, "name");

        expect(model.searchItems[1].custom).toBe(true);
    });
});

// ---------------------------------------------------------------------------
// createNewFavorite
// ---------------------------------------------------------------------------

describe("createNewFavorite", () => {
    test("creates a favorite item and returns serverSideId", async () => {
        const model = makeSearchModel();

        const serverSideId = await createNewFavorite(model, {});

        expect(serverSideId).toBe(42);
        expect(model.searchItems[1].type).toBe("favorite");
        expect(model.searchItems[1].serverSideId).toBe(42);
    });

    test("private favorite gets FAVORITE_PRIVATE_GROUP number", async () => {
        const model = makeSearchModel(); // mock returns userIds: [1]

        await createNewFavorite(model, {});

        expect(model.searchItems[1].groupNumber).toBe(FAVORITE_PRIVATE_GROUP);
    });

    test("shared favorite gets FAVORITE_SHARED_GROUP number", async () => {
        const model = makeSearchModel({
            _getIrFilterDescription: () => ({
                preFavorite: { userIds: [1, 2], domain: "[]", context: {}, orderedBy: [] },
                irFilter: {},
            }),
        });

        await createNewFavorite(model, {});

        expect(model.searchItems[1].groupNumber).toBe(FAVORITE_SHARED_GROUP);
    });

    test("clears existing query before activating the favorite", async () => {
        const model = makeSearchModel();
        model.query = [{ searchItemId: 99 }]; // pre-existing active filter

        await createNewFavorite(model, {});

        // After clearQuery + push favorite: only the new favorite is in query
        expect(model.query.length).toBe(1);
        expect(model.query[0].searchItemId).toBe(1);
    });

    test("increments nextId and nextGroupId after creation", async () => {
        const model = makeSearchModel();
        const idBefore = model.nextId;
        const groupIdBefore = model.nextGroupId;

        await createNewFavorite(model, {});

        expect(model.nextId).toBe(idBefore + 1);
        expect(model.nextGroupId).toBe(groupIdBefore + 1);
    });
});
