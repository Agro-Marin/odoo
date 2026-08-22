// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { condition, connector } from "@web/core/tree/condition_tree";
import { computeSearchItemGroupBys, getQueryGroups } from "@web/search/search_group_by";
import { SearchQueryMixin } from "@web/search/search_query_mixin";
import { SearchSplitDomainMixin } from "@web/search/search_split_domain_mixin";

describe.current.tags("headless");

const QueryModel = SearchSplitDomainMixin(SearchQueryMixin(class {}));

/**
 * @param {Record<string, any>} tree
 * @param {Record<string, any>} [overrides]
 * @returns {any}
 */
function makeSearchModel(tree, overrides = {}) {
    /** @type {string[]} */
    const notifications = [];
    const model = new QueryModel();
    Object.assign(model, {
        query: [],
        searchItems: {},
        searchViewFields: {},
        orderByCount: false,
        blockNotification: false,
        nextId: 1,
        nextGroupId: 1,
        nextGroupNumber: 1,
        resModel: "partner",
        isDebugMode: false,
        defaultGroupBy: undefined,
        env: { config: { viewType: "list" } },
        treeProcessor: {
            treeFromDomain: async () => tree,
            getDomainTreeDescription: async () => "desc",
            getDomainTreeTooltip: async () => "tip",
        },

        _notify() {
            if (this.blockNotification) {
                return;
            }
            notifications.push("notify");
        },
        _getGroups() {
            return getQueryGroups(this.query, this.searchItems);
        },
        /** @returns {Record<string, any>|null} */
        _getSearchItemContext() {
            return null;
        },
        _getSearchItemGroupBys(/** @type {any} */ activeItem) {
            return computeSearchItemGroupBys(activeItem, this.searchItems);
        },
        _notifications: notifications,
        ...overrides,
    });
    return model;
}

/**
 * @param {any} model
 * @param {number} id
 * @param {Record<string, any>} item
 * @param {boolean} [activate]
 */
function addItem(model, id, item, activate = true) {
    model.searchItems[id] = { id, groupId: id, groupNumber: 1, ...item };
    if (activate) {
        model.query.push({ searchItemId: id });
    }
    model.nextId = Math.max(model.nextId, id + 1);
    model.nextGroupId = Math.max(model.nextGroupId, (item.groupId ?? id) + 1);
}

const queryIds = (/** @type {any} */ model) =>
    model.query.map((/** @type {any} */ q) => q.searchItemId);

describe("splitAndAddDomain", () => {
    test("without groupId, new filters are appended after the existing query", async () => {
        const tree = connector("&", [
            condition("foo", "=", 1),
            condition("bar", "=", 2),
        ]);
        const model = makeSearchModel(tree);
        addItem(model, 1, { type: "filter", domain: "[]" });

        await model.splitAndAddDomain(`[("foo", "=", 1), ("bar", "=", 2)]`);

        expect(queryIds(model)).toEqual([1, 2, 3]);
        const created = model.searchItems[2];
        expect(created.type).toBe("filter");
        expect(created.invisible).toBe("True");
        expect(created.description).toBe("desc");
        expect(created.tooltip).toBe("tip");
        expect(model.searchItems[2].groupId).not.toBe(model.searchItems[3].groupId);
        expect(model._notifications.length).toBe(1);
    });

    test("replacing a group keeps its facet position", async () => {
        const tree = connector("&", [
            condition("foo", "=", 1),
            condition("bar", "=", 2),
        ]);
        const model = makeSearchModel(tree);
        addItem(model, 1, { type: "filter", domain: "[]" });
        addItem(model, 2, { type: "filter", domain: "[]" });
        addItem(model, 3, { type: "filter", domain: "[]" });

        await model.splitAndAddDomain(`[("foo", "=", 1), ("bar", "=", 2)]`, 2);

        expect(queryIds(model)).toEqual([1, 4, 5, 3]);
        expect(2 in model.searchItems).toBe(true);
        expect(model.query.some((/** @type {any} */ q) => q.searchItemId === 2)).toBe(
            false,
        );
    });

    test("splitting a favorite recreates its groupBys at the front", async () => {
        const tree = condition("foo", "=", 1);
        const model = makeSearchModel(tree);
        model.searchViewFields = {
            stage_id: { string: "Stage", type: "many2one" },
        };
        addItem(model, 1, { type: "filter", domain: "[]" });
        addItem(model, 2, {
            type: "favorite",
            groupId: 5,
            domain: "[]",
            groupBys: ["stage_id"],
        });

        await model.splitAndAddDomain(`[("foo", "=", 1)]`, 5);

        const groupById = model.query
            .map((/** @type {any} */ q) => model.searchItems[q.searchItemId])
            .find((/** @type {any} */ item) => item.type === "groupBy");
        expect(groupById.fieldName).toBe("stage_id");
        expect(groupById.invisible).toBe("True");
        expect(queryIds(model)).toEqual([groupById.id, 1, 4]);
        expect(model.query.some((/** @type {any} */ q) => q.searchItemId === 2)).toBe(
            false,
        );
    });

    test("a favorite leading the query keeps the leading slot", async () => {
        const tree = condition("foo", "=", 1);
        const model = makeSearchModel(tree);
        model.searchViewFields = {
            stage_id: { string: "Stage", type: "many2one" },
        };
        addItem(model, 2, {
            type: "favorite",
            groupId: 5,
            domain: "[]",
            groupBys: ["stage_id"],
        });
        addItem(model, 1, { type: "filter", domain: "[]" });

        await model.splitAndAddDomain(`[("foo", "=", 1)]`, 5);

        const groupById = model.query
            .map((/** @type {any} */ q) => model.searchItems[q.searchItemId])
            .find((/** @type {any} */ item) => item.type === "groupBy");
        const newFilterId = model.query
            .map((/** @type {any} */ q) => q.searchItemId)
            .find((/** @type {any} */ id) => id !== groupById.id && id !== 1);
        expect(queryIds(model)).toEqual([newFilterId, groupById.id, 1]);
    });

    test("a favorite carrying no groupBys is replaced in place", async () => {
        const tree = condition("foo", "=", 1);
        const model = makeSearchModel(tree);
        addItem(model, 1, { type: "filter", domain: "[]" });
        addItem(model, 2, { type: "favorite", groupId: 5, domain: "[]", groupBys: [] });
        addItem(model, 3, { type: "filter", domain: "[]" });

        await model.splitAndAddDomain(`[("foo", "=", 1)]`, 5);

        const newFilterId = model.query
            .map((/** @type {any} */ q) => q.searchItemId)
            .find((/** @type {any} */ id) => ![1, 3].includes(id));
        expect(queryIds(model)).toEqual([1, newFilterId, 3]);
    });
});
