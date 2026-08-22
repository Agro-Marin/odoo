// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { patchWithCleanup } from "@web/../tests/web_test_helpers";
import { luxon } from "@web/core/l10n/luxon";
import { SearchQueryMixin } from "@web/search/search_query_mixin";
import { SPECIAL } from "@web/search/search_state";

describe.current.tags("headless");

const QueryModel = SearchQueryMixin(class {});

/**
 * @param {Object} [overrides]
 * @returns {any}
 */
function makeSearchModel(overrides = {}) {
    /** @type {string[]} */
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
            if (this.blockNotification) {
                return;
            }
            notifications.push("notify");
        },
        _getSelectedGeneratorIds(/** @type {any} */ searchItemId) {
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
 * @param {Object} model
 * @param {number} id
 * @param {Object} item
 * @param {boolean} [activate]
 */
function addItem(model, id, item, activate = false) {
    model.searchItems[id] = { id, groupId: id, groupNumber: 1, ...item };
    if (activate) {
        model.query.push({ searchItemId: id });
    }
}

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

        expect(model.blockNotification).toBe(true);
    });
});

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

    test("without any fallback group-by, removing the last query group-by clears orderByCount", () => {
        const model = makeSearchModel({ orderByCount: "Desc" });
        addItem(model, 1, { type: "groupBy", groupId: 1 }, true);

        model.deactivateGroup(1);

        expect(model.query.length).toBe(0);
        expect(model.orderByCount).toBe(false);
    });

    test("config-level groupBy keeps orderByCount alive after removing the last query group-by", () => {
        const model = makeSearchModel({
            orderByCount: "Desc",
            globalGroupBy: ["bar"],
        });
        addItem(model, 1, { type: "groupBy", groupId: 1 }, true);

        model.deactivateGroup(1);

        expect(model.query.length).toBe(0);
        expect(model.orderByCount).toBe("Desc");
    });
});

describe("toggleSearchItem", () => {
    test("activates an inactive filter", () => {
        const model = makeSearchModel();
        addItem(model, 1, { type: "filter", groupId: 1 });

        model.toggleSearchItem(1);

        expect(model.query.some((/** @type {any} */ q) => q.searchItemId === 1)).toBe(
            true,
        );
    });

    test("deactivates an active filter", () => {
        const model = makeSearchModel();
        addItem(model, 1, { type: "filter", groupId: 1 }, true);

        model.toggleSearchItem(1);

        expect(model.query.some((/** @type {any} */ q) => q.searchItemId === 1)).toBe(
            false,
        );
    });

    test("activating a favorite clears the query first", () => {
        const model = makeSearchModel();
        addItem(model, 1, { type: "filter", groupId: 1 }, true);
        addItem(model, 2, { type: "favorite", groupId: 2 });

        model.toggleSearchItem(2);

        expect(model.query.length).toBe(1);
        expect(model.query[0].searchItemId).toBe(2);
    });

    test("ignores dateFilter type items", () => {
        const model = makeSearchModel();
        addItem(model, 1, { type: "dateFilter", groupId: 1 });

        model.toggleSearchItem(1);

        expect(model.query.length).toBe(0);
    });

    test("activating a favorite resets orderByCount (no stale __count sort)", () => {
        const model = makeSearchModel({ orderByCount: "Desc" });
        addItem(model, 1, { type: "groupBy", groupId: 1 }, true);
        addItem(model, 2, { type: "favorite", groupId: 2, groupBys: ["state"] });

        model.toggleSearchItem(2);

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

describe("toggleDateFilter", () => {
    test("custom generatorId: replaces any existing entries for the item", () => {
        const model = makeSearchModel();
        addItem(model, 1, { type: "dateFilter" });
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

        model.toggleDateFilter(1, "third_quarter");

        expect(
            model.query.some((/** @type {any} */ q) => q.generatorId === "year"),
        ).toBe(true);
        expect(
            model.query.some(
                (/** @type {any} */ q) => q.generatorId === "third_quarter",
            ),
        ).toBe(false);
    });

    test("removing last year entry clears all remaining entries for that item", () => {
        const model = makeSearchModel();
        addItem(model, 1, { type: "dateFilter" });
        model.query = [{ searchItemId: 1, generatorId: "year" }];

        model.toggleDateFilter(1, "year");

        expect(
            model.query.filter((/** @type {any} */ q) => q.searchItemId === 1).length,
        ).toBe(0);
    });

    test("non-custom add: adds generatorId; with year already present no auto-year", () => {
        const model = makeSearchModel();
        addItem(model, 1, { type: "dateFilter" });
        model.query = [{ searchItemId: 1, generatorId: "year" }];

        model.toggleDateFilter(1, "third_quarter");

        const generatorIds = model.query
            .filter((/** @type {any} */ q) => q.searchItemId === 1)
            .map((/** @type {any} */ q) => q.generatorId);
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
        const model = makeSearchModel();
        addItem(model, 1, { type: "dateFilter" });
        expect(() => model.toggleDateFilter(1, "third_quarter")).not.toThrow();

        const generatorIds = model.query
            .filter((/** @type {any} */ q) => q.searchItemId === 1)
            .map((/** @type {any} */ q) => q.generatorId);
        expect(generatorIds).toInclude("third_quarter");
    });
});

describe("toggleDateFilter generator validation", () => {
    const optionsParams = {
        startYear: -2,
        endYear: 0,
        startMonth: -2,
        endMonth: 0,
        customOptions: [],
    };

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

        const generatorIds = model.query.map((/** @type {any} */ q) => q.generatorId);
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
        const generatorIds = model.query.map((/** @type {any} */ q) => q.generatorId);
        expect(generatorIds).toInclude("month");
        expect(generatorIds).toInclude("year");
        expect(generatorIds).not.toInclude("bogus");
    });
});

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
        expect(model.query.map((/** @type {any} */ q) => q.searchItemId)).toEqual([
            5, 6,
        ]);
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
        expect(model.query.some((/** @type {any} */ q) => q.searchItemId === 1)).toBe(
            true,
        );
    });

    test("date field: creates dateGroupBy item with default interval", () => {
        const model = makeSearchModel();
        model.searchViewFields = { order_date: { string: "Order Date", type: "date" } };

        model.createNewGroupBy("order_date");

        const item = model.searchItems[1];
        expect(item.type).toBe("dateGroupBy");
        expect(item.defaultIntervalId).toBe("month");
    });

    test("uses existing groupBy's groupId when one exists", () => {
        const model = makeSearchModel({ nextGroupId: 3 });
        model.searchViewFields = { name: { string: "Name", type: "char" } };
        model.searchItems[99] = { type: "groupBy", groupId: 7 };

        model.createNewGroupBy("name");

        expect(model.searchItems[1].groupId).toBe(7);
        expect(model.nextGroupId).toBe(3);
    });

    test("joins an existing dateGroupBy's group (unified group-by facet)", () => {
        const model = makeSearchModel({ nextGroupId: 3 });
        model.searchViewFields = { name: { string: "Name", type: "char" } };
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

        expect(model._notifications.length).toBe(1);
    });

    test("date field: notifies exactly once (single reload)", () => {
        const model = makeSearchModel();
        model.searchViewFields = { order_date: { string: "Order Date", type: "date" } };

        model.createNewGroupBy("order_date");

        expect(model._notifications.length).toBe(1);
    });
});

describe("mutator return contract", () => {
    const isThenable = (/** @type {any} */ v) => typeof v?.then === "function";

    function contractModel() {
        const model = makeSearchModel({
            searchViewFields: { foo: { type: "char", string: "Foo" } },
        });
        addItem(model, 1, { type: "field", fieldName: "foo" });
        addItem(model, 2, { type: "filter", domain: "[]" });
        addItem(model, 3, { type: "groupBy", fieldName: "foo" });
        addItem(model, 4, {
            type: "dateFilter",
            fieldName: "date_field",
            defaultGeneratorIds: ["month"],
        });
        addItem(model, 5, {
            type: "dateGroupBy",
            fieldName: "date_field",
            defaultIntervalId: "month",
        });
        model.nextId = 6;
        return model;
    }

    test("every toggler answers a promise on its happy path", () => {
        const model = contractModel();
        expect(isThenable(model.toggleSearchItem(2))).toBe(true);
        expect(isThenable(model.toggleSearchItem(3))).toBe(true);
        expect(isThenable(model.toggleDateFilter(4))).toBe(true);
        expect(isThenable(model.toggleDateGroupBy(5))).toBe(true);
        expect(isThenable(model.clearQuery())).toBe(true);
        expect(isThenable(model.switchGroupBySort())).toBe(true);
        expect(
            isThenable(
                model.addAutoCompletionValues(1, {
                    label: "a",
                    operator: "=",
                    value: "a",
                }),
            ),
        ).toBe(true);
        expect(isThenable(model.deactivateGroup(2))).toBe(true);
    });

    test("every toggler answers a promise on its REFUSAL path too", () => {
        const model = contractModel();
        expect(isThenable(model.toggleSearchItem(1))).toBe(true);
        expect(isThenable(model.toggleSearchItem(4))).toBe(true);
        expect(isThenable(model.toggleSearchItem(5))).toBe(true);
        expect(isThenable(model.toggleDateFilter(2))).toBe(true);
        expect(isThenable(model.toggleDateGroupBy(2))).toBe(true);
        expect(
            isThenable(
                model.addAutoCompletionValues(2, {
                    label: "a",
                    operator: "=",
                    value: "a",
                }),
            ),
        ).toBe(true);
    });

    test("an invalid search item is refused, and still answers a promise", () => {
        const model = contractModel();
        addItem(model, 9, { type: "filter", domain: "[]", isInvalid: true });
        expect(isThenable(model.toggleSearchItem(9))).toBe(true);
        expect(model.query).toEqual([]);
    });

    test("creators stay synchronous, because splitAndAddDomain reads their ids", () => {
        const model = contractModel();
        const filterIds = model.createNewFilters([{ description: "x", domain: "[]" }]);
        expect(Array.isArray(filterIds)).toBe(true);
        expect(filterIds).toHaveLength(1);

        expect(typeof model.createNewGroupBy("foo")).toBe("number");
        expect(model.createNewGroupBy("no_such_field")).toBe(undefined);
    });
});
