// @ts-check

/**
 * Unit tests for search/search_query_mixin.js.
 *
 * The query-mutation logic is a mixin applied to SearchModel; it is exercised
 * here on a bare SearchQueryMixin(class {}) instance with minimal state and a
 * couple of stubs (_notify, _getSelectedGeneratorIds). Because the methods use
 * `this`, an instance is all that is needed.
 * spawnCustomFilterDialog isn't tested here — it needs a dialog service and is
 * covered by integration tests. (Favorite creation is in
 * search_favorites_mixin.test.js.)
 */

import { describe, expect, test } from "@odoo/hoot";
import { patchWithCleanup } from "@web/../tests/web_test_helpers";
import { luxon } from "@web/core/l10n/luxon";
import { SearchQueryMixin } from "@web/search/search_query_mixin";
import { SPECIAL } from "@web/search/search_state";

// Helpers

/** Concrete class exercising the mixin methods in isolation. */
const QueryModel = SearchQueryMixin(class {});

/**
 * Minimal SearchModel-like instance for the query-mutation mixin methods.
 * @param {Object} [overrides]
 * @returns {Object}
 */
function makeSearchModel(overrides = {}) {
    const notifications = [];
    const model = new QueryModel();
    Object.assign(model, {
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
            // Mirror the real SearchModel: a blocked notification is a no-op,
            // so tests can assert how many *reloads* an operation triggers.
            if (this.blockNotification) {
                return;
            }
            notifications.push("notify");
        },
        /** Derive selected generatorIds live from query so tests stay realistic. */
        _getSelectedGeneratorIds(searchItemId) {
            return this.query
                .filter((q) => q.searchItemId === searchItemId && "generatorId" in q)
                .map((q) => q.generatorId);
        },
        _notifications: notifications,
        ...overrides,
    });
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

// addAutoCompletionValues

describe("addAutoCompletionValues", () => {
    test("adds a new autocomplete value to query", () => {
        const model = makeSearchModel();
        addItem(model, 1, { type: "field" });

        model.addAutoCompletionValues(1, {
            label: "Alice",
            value: "Alice",
            operator: "=",
        });

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
        model.query.push({
            searchItemId: 1,
            autocompleteValue: { label: "Old", value: "Alice", operator: "=" },
        });

        model.addAutoCompletionValues(1, {
            label: "New",
            value: "Alice",
            operator: "=",
        });

        // no duplicate added
        expect(model.query.length).toBe(1);
        expect(model.query[0].autocompleteValue.label).toBe("New");
    });

    test("ignores non-field search items", () => {
        const model = makeSearchModel();
        addItem(model, 1, { type: "filter" });

        model.addAutoCompletionValues(1, { label: "X", value: "X", operator: "=" });

        expect(model.query.length).toBe(0);
    });

    test("calls _notify", () => {
        const model = makeSearchModel();
        addItem(model, 1, { type: "field" });

        model.addAutoCompletionValues(1, { label: "A", value: "A", operator: "=" });

        expect(model._notifications.length).toBeGreaterThan(0);
    });
});

// clearQuery

describe("clearQuery", () => {
    test("empties the query array", () => {
        const model = makeSearchModel();
        model.query = [{ searchItemId: 1 }, { searchItemId: 2 }];

        model.clearQuery();

        expect(model.query.length).toBe(0);
    });

    test("resets orderByCount to false", () => {
        const model = makeSearchModel({ orderByCount: "Desc" });

        model.clearQuery();

        expect(model.orderByCount).toBe(false);
    });
});

// clearFilters

describe("clearFilters", () => {
    test("removes non-groupBy facets from query", () => {
        const model = makeSearchModel();
        addItem(model, 1, { type: "filter", groupId: 1 }, true);
        addItem(model, 2, { type: "groupBy", groupId: 2 }, true);
        model.facets = [
            { type: "filter", groupId: 1 },
            { type: "groupBy", groupId: 2 },
        ];

        model.clearFilters();

        // groupBy (id=2) must remain; filter (id=1) must be gone
        expect(model.query.some((q) => q.searchItemId === 2)).toBe(true);
        expect(model.query.some((q) => q.searchItemId === 1)).toBe(false);
    });

    test("leaves groupBy facets untouched", () => {
        const model = makeSearchModel();
        addItem(model, 10, { type: "groupBy", groupId: 10 }, true);
        model.facets = [{ type: "groupBy", groupId: 10 }];

        model.clearFilters();

        expect(model.query.length).toBe(1);
        expect(model.query[0].searchItemId).toBe(10);
    });

    test("a throwing facets getter does not permanently silence the model", () => {
        const model = makeSearchModel();
        // Simulate a corrupt favorite whose stored domain fails to parse while
        // the facets getter runs inside the notifications-blocked window.
        Object.defineProperty(model, "facets", {
            configurable: true,
            get() {
                throw new Error("unparseable domain");
            },
        });

        expect(() => model.clearFilters()).toThrow();

        // blockNotification must have been reset by the try/finally, so a
        // subsequent search still notifies rather than being silenced forever.
        expect(model.blockNotification).toBe(false);
        const before = model._notifications.length;
        model.clearQuery();
        expect(model._notifications.length).toBe(before + 1);
    });
});

// withNotificationsBlocked

describe("withNotificationsBlocked", () => {
    test("suppresses notifications inside the window", () => {
        const model = makeSearchModel();

        model._withNotificationsBlocked(() => {
            model._notify();
            model._notify();
        });

        expect(model._notifications.length).toBe(0);
    });

    test("resets blockNotification even when the callback throws", () => {
        const model = makeSearchModel();

        expect(() =>
            model._withNotificationsBlocked(() => {
                throw new Error("boom");
            }),
        ).toThrow();

        expect(model.blockNotification).toBe(false);
    });

    test("restores the previous blocked state (nesting-safe)", () => {
        const model = makeSearchModel({ blockNotification: true });

        model._withNotificationsBlocked(() => {
            expect(model.blockNotification).toBe(true);
        });

        // Restored to the captured value, not hardcoded false.
        expect(model.blockNotification).toBe(true);
    });
});

// deactivateGroup

describe("deactivateGroup", () => {
    test("removes all query elements with matching groupId", () => {
        const model = makeSearchModel();
        addItem(model, 1, { type: "filter", groupId: 5 }, true);
        addItem(model, 2, { type: "filter", groupId: 5 }, true);
        addItem(model, 3, { type: "filter", groupId: 6 }, true);

        model.deactivateGroup(5);

        expect(model.query.length).toBe(1);
        expect(model.query[0].searchItemId).toBe(3);
    });

    test("SPECIAL groupId removes defaultGroupBy property", () => {
        const model = makeSearchModel();
        model.defaultGroupBy = ["name"];

        model.deactivateGroup(SPECIAL);

        expect("defaultGroupBy" in model).toBe(false);
    });

    test("no-op when groupId not present in query", () => {
        const model = makeSearchModel();
        addItem(model, 1, { type: "filter", groupId: 1 }, true);

        model.deactivateGroup(99);

        expect(model.query.length).toBe(1);
    });
});

// toggleSearchItem

describe("toggleSearchItem", () => {
    test("activates an inactive filter", () => {
        const model = makeSearchModel();
        addItem(model, 1, { type: "filter", groupId: 1 });

        model.toggleSearchItem(1);

        expect(model.query.some((q) => q.searchItemId === 1)).toBe(true);
    });

    test("deactivates an active filter", () => {
        const model = makeSearchModel();
        addItem(model, 1, { type: "filter", groupId: 1 }, true);

        model.toggleSearchItem(1);

        expect(model.query.some((q) => q.searchItemId === 1)).toBe(false);
    });

    test("activating a favorite clears the query first", () => {
        const model = makeSearchModel();
        addItem(model, 1, { type: "filter", groupId: 1 }, true);
        addItem(model, 2, { type: "favorite", groupId: 2 });

        model.toggleSearchItem(2);

        // Only the favorite is active; the filter was cleared
        expect(model.query.length).toBe(1);
        expect(model.query[0].searchItemId).toBe(2);
    });

    test("ignores dateFilter type items", () => {
        const model = makeSearchModel();
        addItem(model, 1, { type: "dateFilter", groupId: 1 });

        model.toggleSearchItem(1);

        // dateFilter is silently ignored
        expect(model.query.length).toBe(0);
    });

    test("activating a favorite resets orderByCount (no stale __count sort)", () => {
        const model = makeSearchModel({ orderByCount: "Desc" });
        addItem(model, 1, { type: "groupBy", groupId: 1 }, true);
        addItem(model, 2, { type: "favorite", groupId: 2, groupBys: ["state"] });

        model.toggleSearchItem(2);

        // Only the favorite is active, and the count sort it never carried is
        // cleared so computeOrderBy won't inject {name:"__count"}.
        expect(model.query.length).toBe(1);
        expect(model.query[0].searchItemId).toBe(2);
        expect(model.orderByCount).toBe(false);
    });

    test("ignores items flagged isInvalid (e.g. corrupt favorite)", () => {
        const model = makeSearchModel();
        addItem(model, 1, { type: "favorite", groupId: 1, isInvalid: true });

        model.toggleSearchItem(1);

        expect(model.query.length).toBe(0);
    });
});

// toggleDateGroupBy

describe("toggleDateGroupBy", () => {
    test("adds intervalId entry to query when not present", () => {
        const model = makeSearchModel();
        addItem(model, 1, { type: "dateGroupBy", defaultIntervalId: "month" });

        model.toggleDateGroupBy(1, "month");

        expect(model.query).toEqual([{ searchItemId: 1, intervalId: "month" }]);
    });

    test("uses defaultIntervalId when intervalId not given", () => {
        const model = makeSearchModel();
        addItem(model, 1, { type: "dateGroupBy", defaultIntervalId: "week" });

        model.toggleDateGroupBy(1);

        expect(model.query[0].intervalId).toBe("week");
    });

    test("removes intervalId entry when already active", () => {
        const model = makeSearchModel();
        addItem(model, 1, { type: "dateGroupBy", defaultIntervalId: "month" });
        model.query.push({ searchItemId: 1, intervalId: "month" });

        model.toggleDateGroupBy(1, "month");

        expect(model.query.length).toBe(0);
    });

    test("ignores non-dateGroupBy items", () => {
        const model = makeSearchModel();
        addItem(model, 1, { type: "groupBy", defaultIntervalId: "month" });

        model.toggleDateGroupBy(1, "month");

        expect(model.query.length).toBe(0);
    });
});

// toggleDateFilter

describe("toggleDateFilter", () => {
    test("custom generatorId: replaces any existing entries for the item", () => {
        const model = makeSearchModel();
        addItem(model, 1, { type: "dateFilter" });
        // pre-populate another entry for the same item
        model.query.push({ searchItemId: 1, generatorId: "custom_old" });

        model.toggleDateFilter(1, "custom_2024_01_01");

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
        model.toggleDateFilter(1, "third_quarter");

        expect(model.query.some((q) => q.generatorId === "year")).toBe(true);
        expect(model.query.some((q) => q.generatorId === "third_quarter")).toBe(false);
    });

    test("removing last year entry clears all remaining entries for that item", () => {
        const model = makeSearchModel();
        addItem(model, 1, { type: "dateFilter" });
        model.query = [{ searchItemId: 1, generatorId: "year" }];

        model.toggleDateFilter(1, "year");

        expect(model.query.filter((q) => q.searchItemId === 1).length).toBe(0);
    });

    test("non-custom add: adds generatorId; with year already present no auto-year", () => {
        const model = makeSearchModel();
        addItem(model, 1, { type: "dateFilter" });
        // Pre-seed a year so yearSelected() returns true → getPeriodOptions not called
        model.query = [{ searchItemId: 1, generatorId: "year" }];

        model.toggleDateFilter(1, "third_quarter");

        const generatorIds = model.query
            .filter((q) => q.searchItemId === 1)
            .map((q) => q.generatorId);
        expect(generatorIds).toInclude("third_quarter");
        expect(generatorIds).toInclude("year");
    });

    test("ignores non-dateFilter items", () => {
        const model = makeSearchModel();
        addItem(model, 1, { type: "filter" });

        model.toggleDateFilter(1, "year");

        expect(model.query.length).toBe(0);
    });

    test("non-custom add without optionsParams and no year selected: does not throw", () => {
        // Regression: a bare searchItem with no optionsParams (e.g. a
        // directly-toggled explicit generatorId, or a unit-test item) must
        // not crash. The top validation call is guarded by
        // `if (searchItem.optionsParams)`, but the defaultYearId lookup
        // further down in this same branch calls getPeriodOptions()
        // unconditionally whenever no year is yet selected — that call
        // destructures optionsParams and throws when it is undefined.
        const model = makeSearchModel();
        addItem(model, 1, { type: "dateFilter" });
        // No pre-existing "year" entry, so yearSelected() is false and the
        // defaultYearId lookup branch runs.
        expect(() => model.toggleDateFilter(1, "third_quarter")).not.toThrow();

        const generatorIds = model.query
            .filter((q) => q.searchItemId === 1)
            .map((q) => q.generatorId);
        expect(generatorIds).toInclude("third_quarter");
    });
});

// toggleDateFilter — generator id validation (fork-added, console.warn contract)

describe("toggleDateFilter generator validation", () => {
    const optionsParams = {
        startYear: -2,
        endYear: 0,
        startMonth: -2,
        endMonth: 0,
        customOptions: [],
    };

    /** Model with a referenceMoment so getPeriodOptions can run. */
    function makeDateModel() {
        return makeSearchModel({ referenceMoment: luxon.DateTime.local() });
    }

    test("unknown generator id is dropped with a warning (filter stays inactive)", () => {
        patchWithCleanup(console, { warn: () => expect.step("warn") });
        const model = makeDateModel();
        addItem(model, 1, { type: "dateFilter", name: "filter_date", optionsParams });

        model.toggleDateFilter(1, "bogus");

        expect.verifySteps(["warn"]);
        expect(model.query.length).toBe(0);
    });

    test("known generator id activates the option plus its default year", () => {
        const model = makeDateModel();
        addItem(model, 1, { type: "dateFilter", name: "filter_date", optionsParams });

        model.toggleDateFilter(1, "month");

        const generatorIds = model.query.map((q) => q.generatorId);
        expect(generatorIds).toInclude("month");
        expect(generatorIds).toInclude("year");
    });

    test("unknown ids in defaultGeneratorIds are filtered, valid ones proceed", () => {
        patchWithCleanup(console, { warn: () => expect.step("warn") });
        const model = makeDateModel();
        addItem(model, 1, {
            type: "dateFilter",
            name: "filter_date",
            optionsParams,
            defaultGeneratorIds: ["month", "bogus"],
        });

        model.toggleDateFilter(1);

        expect.verifySteps(["warn"]);
        const generatorIds = model.query.map((q) => q.generatorId);
        expect(generatorIds).toInclude("month");
        expect(generatorIds).toInclude("year");
        expect(generatorIds).not.toInclude("bogus");
    });
});

// switchGroupBySort

describe("switchGroupBySort", () => {
    test("starts at false, first switch → Desc", () => {
        const model = makeSearchModel({ orderByCount: false });

        model.switchGroupBySort();

        expect(model.orderByCount).toBe("Desc");
    });

    test("Desc → Asc", () => {
        const model = makeSearchModel({ orderByCount: "Desc" });

        model.switchGroupBySort();

        expect(model.orderByCount).toBe("Asc");
    });

    test("Asc → Desc", () => {
        const model = makeSearchModel({ orderByCount: "Asc" });

        model.switchGroupBySort();

        expect(model.orderByCount).toBe("Desc");
    });
});

// createNewFilters

describe("createNewFilters", () => {
    test("creates filter items and activates them in query", () => {
        const model = makeSearchModel();
        const prefilters = [
            { description: "Active", domain: "[['active','=',true]]" },
            { description: "Draft", domain: "[['state','=','draft']]" },
        ];

        model.createNewFilters(prefilters);

        expect(Object.keys(model.searchItems).length).toBe(2);
        expect(model.query.length).toBe(2);
        expect(model.searchItems[1].type).toBe("filter");
        expect(model.searchItems[2].type).toBe("filter");
    });

    test("assigns sequential IDs starting from nextId", () => {
        const model = makeSearchModel({ nextId: 5 });

        model.createNewFilters([{ description: "X", domain: "[]" }]);

        expect(5 in model.searchItems).toBe(true);
        expect(model.nextId).toBe(6);
    });

    test("returns [] for empty prefilters and does not call _notify", () => {
        const model = makeSearchModel();

        const ids = model.createNewFilters([]);

        expect(ids).toEqual([]);
        expect(model.query.length).toBe(0);
        expect(model._notifications.length).toBe(0);
    });

    test("returns the ids of the created items", () => {
        const model = makeSearchModel({ nextId: 5 });

        const ids = model.createNewFilters([
            { description: "A", domain: "[]" },
            { description: "B", domain: "[]" },
        ]);

        expect(ids).toEqual([5, 6]);
        expect(model.query.map((q) => q.searchItemId)).toEqual([5, 6]);
    });

    test("all filters share the same groupId and groupNumber", () => {
        const model = makeSearchModel();

        model.createNewFilters([
            { description: "A", domain: "[]" },
            { description: "B", domain: "[]" },
        ]);

        expect(model.searchItems[1].groupId).toBe(model.searchItems[2].groupId);
        expect(model.searchItems[1].groupNumber).toBe(model.searchItems[2].groupNumber);
    });
});

// createNewGroupBy

describe("createNewGroupBy", () => {
    test("non-date field: creates groupBy item and activates it", () => {
        const model = makeSearchModel();
        model.searchViewFields = {
            partner_id: { string: "Partner", type: "many2one" },
        };

        model.createNewGroupBy("partner_id");

        const item = model.searchItems[1];
        expect(item.type).toBe("groupBy");
        expect(item.fieldName).toBe("partner_id");
        expect(model.query.some((q) => q.searchItemId === 1)).toBe(true);
    });

    test("date field: creates dateGroupBy item with default interval", () => {
        const model = makeSearchModel();
        model.searchViewFields = { order_date: { string: "Order Date", type: "date" } };

        model.createNewGroupBy("order_date");

        const item = model.searchItems[1];
        expect(item.type).toBe("dateGroupBy");
        expect(item.defaultIntervalId).toBe("month"); // DEFAULT_INTERVAL
    });

    test("uses existing groupBy's groupId when one exists", () => {
        const model = makeSearchModel({ nextGroupId: 3 });
        model.searchViewFields = { name: { string: "Name", type: "char" } };
        // Pre-existing groupBy item with groupId = 7
        model.searchItems[99] = { type: "groupBy", groupId: 7 };

        model.createNewGroupBy("name");

        // New item should reuse groupId 7, NOT allocate nextGroupId
        expect(model.searchItems[1].groupId).toBe(7);
        // nextGroupId should NOT have been consumed
        expect(model.nextGroupId).toBe(3);
    });

    test("joins an existing dateGroupBy's group (unified group-by facet)", () => {
        const model = makeSearchModel({ nextGroupId: 3 });
        model.searchViewFields = { name: { string: "Name", type: "char" } };
        // Only a date group-by pre-exists; the arch parser would have unified it
        // with plain group-bys into one group, so the custom group-by must reuse
        // its groupId rather than open a second, separate group-by facet.
        model.searchItems[99] = { type: "dateGroupBy", groupId: 7 };

        model.createNewGroupBy("name");

        expect(model.searchItems[1].groupId).toBe(7);
        expect(model.nextGroupId).toBe(3);
    });

    test("custom flag is set on new item", () => {
        const model = makeSearchModel();
        model.searchViewFields = { name: { string: "Name", type: "char" } };

        model.createNewGroupBy("name");

        expect(model.searchItems[1].custom).toBe(true);
    });

    test("returns the id of the created item", () => {
        const model = makeSearchModel({ nextId: 4 });
        model.searchViewFields = { name: { string: "Name", type: "char" } };

        expect(model.createNewGroupBy("name")).toBe(4);
    });

    test("non-date field: notifies exactly once (single reload)", () => {
        const model = makeSearchModel();
        model.searchViewFields = { name: { string: "Name", type: "char" } };

        model.createNewGroupBy("name");

        // The inner toggleSearchItem._notify() is blocked; only the trailing
        // _notify() fires — "Add Custom Group" must not double-reload.
        expect(model._notifications.length).toBe(1);
    });

    test("date field: notifies exactly once (single reload)", () => {
        const model = makeSearchModel();
        model.searchViewFields = { order_date: { string: "Order Date", type: "date" } };

        model.createNewGroupBy("order_date");

        expect(model._notifications.length).toBe(1);
    });
});
