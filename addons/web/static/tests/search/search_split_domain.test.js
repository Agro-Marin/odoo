// @ts-check

/**
 * Pure unit tests for search/search_split_domain.js.
 *
 * splitAndAddDomain receives the SearchModel as first argument (delegation
 * pattern); tests use a minimal mock whose query-mutation methods delegate to
 * the real search_query_mutations functions, so the query-order observable
 * (which drives facet order) is exercised through the genuine chain. The
 * treeProcessor is stubbed: trees are built with the real condition_tree
 * helpers so domainFromTree runs unmocked.
 */

import { describe, expect, test } from "@odoo/hoot";
import { condition, connector } from "@web/core/tree/condition_tree";
import { computeSearchItemGroupBys, getQueryGroups } from "@web/search/search_group_by";
import {
    createNewFilters,
    createNewGroupBy,
    deactivateGroup,
    toggleDateGroupBy,
    toggleSearchItem,
} from "@web/search/search_query_mutations";
import { splitAndAddDomain } from "@web/search/search_split_domain";

describe.current.tags("headless");

/**
 * Build a minimal SearchModel mock around a stubbed treeProcessor.
 * @param {Object} tree - tree returned by treeFromDomain
 * @param {Object} [overrides]
 */
function makeSearchModel(tree, overrides = {}) {
    const notifications = [];
    const model = {
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
        _getSearchItemContext() {
            return null;
        },
        _getSearchItemGroupBys(activeItem) {
            return computeSearchItemGroupBys(activeItem, this.searchItems);
        },
        deactivateGroup(groupId) {
            deactivateGroup(this, groupId);
        },
        createNewFilters(prefilters) {
            return createNewFilters(this, prefilters);
        },
        createNewGroupBy(fieldName, options) {
            return createNewGroupBy(this, fieldName, options);
        },
        toggleSearchItem(id) {
            toggleSearchItem(this, id);
        },
        toggleDateGroupBy(id, intervalId) {
            toggleDateGroupBy(this, id, intervalId);
        },

        _notifications: notifications,
        ...overrides,
    };
    return model;
}

/**
 * Add a search item and (optionally) activate it in the query.
 * @param {Object} model
 * @param {number} id
 * @param {Object} item
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

const queryIds = (model) => model.query.map((q) => q.searchItemId);

describe("splitAndAddDomain", () => {
    test("without groupId, new filters are appended after the existing query", async () => {
        const tree = connector("&", [
            condition("foo", "=", 1),
            condition("bar", "=", 2),
        ]);
        const model = makeSearchModel(tree);
        addItem(model, 1, { type: "filter", domain: "[]" });

        await splitAndAddDomain(model, `[("foo", "=", 1), ("bar", "=", 2)]`);

        expect(queryIds(model)).toEqual([1, 2, 3]);
        const created = model.searchItems[2];
        expect(created.type).toBe("filter");
        expect(created.invisible).toBe("True");
        expect(created.description).toBe("desc");
        expect(created.tooltip).toBe("tip");
        // Each split condition gets its own group (own facet).
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

        await splitAndAddDomain(model, `[("foo", "=", 1), ("bar", "=", 2)]`, 2);

        // The two new filters (ids 4, 5) take the replaced group's position.
        expect(queryIds(model)).toEqual([1, 4, 5, 3]);
        expect(2 in model.searchItems).toBe(true); // item stays, group inactive
        expect(model.query.some((q) => q.searchItemId === 2)).toBe(false);
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

        await splitAndAddDomain(model, `[("foo", "=", 1)]`, 5);

        // Pinned observable: recreated groupBy first, then the new filter at
        // the favorite's (pre-rotation) position, then the other groups.
        const groupById = model.query
            .map((q) => model.searchItems[q.searchItemId])
            .find((item) => item.type === "groupBy");
        expect(groupById.fieldName).toBe("stage_id");
        expect(groupById.invisible).toBe("True");
        expect(queryIds(model)).toEqual([groupById.id, 4, 1]);
        expect(model.query.some((q) => q.searchItemId === 2)).toBe(false);
    });
});
