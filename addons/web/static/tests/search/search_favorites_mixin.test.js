// @ts-check

/**
 * Unit tests for search/search_favorites_mixin.js.
 *
 * The favorite logic is a mixin applied to SearchModel; it is exercised here on
 * a bare SearchFavoritesMixin(class {}) instance with a minimal set of state and
 * stubs (_createIrFilters / _getIrFilterDescription — the ORM- and env-bound
 * pieces) assigned. Because the methods use `this`, an instance is all that is
 * needed.
 *
 * The reconcile/description/tree paths (_reconciliateFavorites,
 * _getIrFilterDescription, _createGroupOfFavorites) involve env callbacks and
 * server data and are covered by the search_panel / favorites integration tests.
 */

import { describe, expect, test } from "@odoo/hoot";
import { SearchFavoritesMixin } from "@web/search/search_favorites_mixin";
import {
    FAVORITE_PRIVATE_GROUP,
    FAVORITE_SHARED_GROUP,
} from "@web/search/search_state";

/** Concrete class exercising the mixin methods in isolation. */
const FavoritesModel = SearchFavoritesMixin(class {});

/**
 * Build a minimal SearchModel-like instance for the favorite mixin methods.
 * @param {Object} [overrides]
 */
function makeSearchModel(overrides = {}) {
    const notifications = [];
    const model = new FavoritesModel();
    Object.assign(model, {
        searchItems: {},
        query: [],
        nextId: 1,
        nextGroupId: 1,
        blockNotification: false,
        _notify() {
            if (this.blockNotification) {
                return;
            }
            notifications.push("notify");
        },
        clearQuery() {
            this.query = [];
        },
        // Provided by SearchQueryMixin in the real SearchModel stack; stubbed
        // here since this suite exercises SearchFavoritesMixin in isolation.
        _withNotificationsBlocked(fn) {
            const wasBlocked = this.blockNotification;
            this.blockNotification = true;
            try {
                fn();
            } finally {
                this.blockNotification = wasBlocked;
            }
        },
        // Stub: returns a serverSideId without a real ORM call.
        _createIrFilters: async () => 42,
        // Stub: always returns a private-user preFavorite.
        _getIrFilterDescription: () => ({
            preFavorite: { userIds: [1], domain: "[]", context: {}, orderedBy: [] },
            irFilter: { name: "My Fav", domain: "[]", context: {} },
        }),
        _notifications: notifications,
        ...overrides,
    });
    return model;
}

// createNewFavorite

describe("createNewFavorite", () => {
    test("creates a favorite item and returns serverSideId", async () => {
        const model = makeSearchModel();

        const serverSideId = await model.createNewFavorite({});

        expect(serverSideId).toBe(42);
        expect(model.searchItems[1].type).toBe("favorite");
        expect(model.searchItems[1].serverSideId).toBe(42);
    });

    test("private favorite gets FAVORITE_PRIVATE_GROUP number", async () => {
        const model = makeSearchModel(); // mock returns userIds: [1]

        await model.createNewFavorite({});

        expect(model.searchItems[1].groupNumber).toBe(FAVORITE_PRIVATE_GROUP);
    });

    test("shared favorite gets FAVORITE_SHARED_GROUP number", async () => {
        const model = makeSearchModel({
            _getIrFilterDescription: () => ({
                preFavorite: {
                    userIds: [1, 2],
                    domain: "[]",
                    context: {},
                    orderedBy: [],
                },
                irFilter: {},
            }),
        });

        await model.createNewFavorite({});

        expect(model.searchItems[1].groupNumber).toBe(FAVORITE_SHARED_GROUP);
    });

    test("clears existing query before activating the favorite", async () => {
        const model = makeSearchModel();
        model.query = [{ searchItemId: 99 }]; // pre-existing active filter

        await model.createNewFavorite({});

        // After clearQuery + push favorite: only the new favorite is in query
        expect(model.query.length).toBe(1);
        expect(model.query[0].searchItemId).toBe(1);
    });

    test("increments nextId and nextGroupId after creation", async () => {
        const model = makeSearchModel();
        const idBefore = model.nextId;
        const groupIdBefore = model.nextGroupId;

        await model.createNewFavorite({});

        expect(model.nextId).toBe(idBefore + 1);
        expect(model.nextGroupId).toBe(groupIdBefore + 1);
    });
});
