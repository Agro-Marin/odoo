// @ts-check

/**
 * Pure unit tests for search/search_favorites.js: ir.filters → favorite
 * conversion (including the isInvalid quarantine paths), the favorite →
 * ir.filters description round-trip, and favorite reconciliation on state
 * import.
 */

import { describe, expect, test } from "@odoo/hoot";
import {
    buildIrFilterDescription,
    irFilterToFavorite,
    reconciliateFavorites,
} from "@web/search/search_favorites";
import {
    FAVORITE_PRIVATE_GROUP,
    FAVORITE_SHARED_GROUP,
} from "@web/search/search_state";

describe.current.tags("headless");

/** Build a well-formed ir.filters record (as returned by get_filters). */
function makeIrFilter(overrides = {}) {
    return {
        id: 7,
        name: "My favorite",
        user_ids: [2],
        context: "{}",
        domain: "[('foo', '=', 1)]",
        sort: '["foo", "bar desc"]',
        is_default: false,
        ...overrides,
    };
}

describe("irFilterToFavorite", () => {
    test("converts a valid ir.filter", () => {
        const favorite = irFilterToFavorite(makeIrFilter({ is_default: true }));

        expect(favorite.isInvalid).toBe(false);
        expect(favorite.description).toBe("My favorite");
        expect(favorite.serverSideId).toBe(7);
        expect(favorite.groupNumber).toBe(FAVORITE_PRIVATE_GROUP);
        expect(favorite.isDefault).toBe(true);
        expect(favorite.orderBy).toEqual([
            { asc: true, name: "foo" },
            { asc: false, name: "bar" },
        ]);
    });

    test("supports the '-field' orderBy notation and shared group number", () => {
        const favorite = irFilterToFavorite(
            makeIrFilter({ user_ids: [], sort: '["-foo"]' }),
        );

        expect(favorite.groupNumber).toBe(FAVORITE_SHARED_GROUP);
        expect(favorite.orderBy).toEqual([{ asc: false, name: "foo" }]);
    });

    test("extracts group_by from the context", () => {
        const favorite = irFilterToFavorite(
            makeIrFilter({ context: "{'group_by': ['stage_id'], 'keep': 1}" }),
        );

        expect(favorite.groupBys).toEqual(["stage_id"]);
        expect(favorite.context).toEqual({ keep: 1 });
    });

    test("quarantines an unparseable context", () => {
        const favorite = irFilterToFavorite(makeIrFilter({ context: "{'invalid" }));

        expect(favorite.isInvalid).toBe(true);
        expect(favorite.context).toEqual({});
    });

    test("quarantines an unparseable domain", () => {
        const favorite = irFilterToFavorite(makeIrFilter({ domain: "[(" }));

        expect(favorite.isInvalid).toBe(true);
    });

    test("quarantines a non-array sort blob instead of crashing", () => {
        // JSON.parse(false) → false without throwing; sort.map would TypeError.
        const favorite = irFilterToFavorite(makeIrFilter({ sort: "false" }));

        expect(favorite.isInvalid).toBe(true);
        expect(favorite.orderBy).toEqual([]);
    });

    test("a quarantined favorite never becomes the default", () => {
        const favorite = irFilterToFavorite(
            makeIrFilter({ sort: "false", is_default: true }),
        );

        expect(favorite.isDefault).toBe(undefined);
    });
});

describe("buildIrFilterDescription", () => {
    /** Minimal params for buildIrFilterDescription. */
    function makeParams(overrides = {}) {
        return {
            description: "Sales this year",
            isDefault: true,
            isShared: true,
            localContext: {},
            getContext: () => ({ custom_key: 1, search_default_x: 1 }),
            getDomain: () => ({ toString: () => "[('x', '=', 1)]" }),
            getGroupBy: () => ["stage_id", "date:month"],
            getOrderBy: () => [
                { name: "foo", asc: true },
                { name: "bar", asc: false },
            ],
            globalContext: {},
            actionId: 55,
            resModel: "res.partner",
            ...overrides,
        };
    }

    test("serializes orderBy in 'field desc' notation and strips defaults", () => {
        const { irFilter } = buildIrFilterDescription(makeParams());

        expect(irFilter.sort).toBe('["foo","bar desc"]');
        expect(irFilter.context.group_by).toEqual(["stage_id", "date:month"]);
        expect(irFilter.context.custom_key).toBe(1);
        expect("search_default_x" in irFilter.context).toBe(false);
        expect(irFilter.user_ids).toEqual([]);
        expect(irFilter.is_default).toBe(true);
    });

    test("round-trips through irFilterToFavorite", () => {
        const { irFilter } = buildIrFilterDescription(makeParams());

        // get_filters serializes the context back to a string.
        const favorite = irFilterToFavorite({
            ...irFilter,
            id: 1,
            context: JSON.stringify(irFilter.context),
        });

        expect(favorite.isInvalid).toBe(false);
        expect(favorite.description).toBe("Sales this year");
        expect(favorite.groupBys).toEqual(["stage_id", "date:month"]);
        expect(favorite.orderBy).toEqual([
            { asc: true, name: "foo" },
            { asc: false, name: "bar" },
        ]);
        expect(favorite.domain).toBe("[('x', '=', 1)]");
        expect(favorite.isDefault).toBe(true);
        expect(favorite.groupNumber).toBe(FAVORITE_SHARED_GROUP);
    });
});

describe("reconciliateFavorites", () => {
    test("replaces a changed favorite instead of merging stale keys", () => {
        const searchItems = {
            3: {
                id: 3,
                groupId: 9,
                type: "favorite",
                serverSideId: 7,
                isDefault: true,
                description: "Old name",
            },
        };
        const query = [{ searchItemId: 3 }];

        reconciliateFavorites(
            searchItems,
            query,
            [makeIrFilter({ is_default: false, name: "New name" })],
            irFilterToFavorite,
            () => {},
        );

        expect(searchItems[3].id).toBe(3);
        expect(searchItems[3].groupId).toBe(9);
        expect(searchItems[3].description).toBe("New name");
        // A merge would have kept the stale isDefault: true.
        expect("isDefault" in searchItems[3]).toBe(false);
        expect(query).toEqual([{ searchItemId: 3 }]);
    });

    test("removes favorites deleted server-side, along with their query entries", () => {
        const searchItems = {
            3: { id: 3, groupId: 9, type: "favorite", serverSideId: 7 },
        };
        const query = [{ searchItemId: 3 }];

        reconciliateFavorites(searchItems, query, [], irFilterToFavorite, () => {});

        expect(3 in searchItems).toBe(false);
        expect(query).toEqual([]);
    });

    test("creates favorites that only exist server-side", () => {
        const created = [];
        reconciliateFavorites(
            {},
            [],
            [makeIrFilter()],
            irFilterToFavorite,
            (irFilters) => created.push(...irFilters),
        );

        expect(created.length).toBe(1);
        expect(created[0].id).toBe(7);
    });
});
