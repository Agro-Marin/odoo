// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { makeCompositionDouble } from "@web/../tests/search/search_doubles";
import { SearchFavoritesMixin } from "@web/search/search_favorites_mixin";
import {
    FAVORITE_PRIVATE_GROUP,
    FAVORITE_SHARED_GROUP,
} from "@web/search/search_state";

describe.current.tags("headless");

const FavoritesModel = SearchFavoritesMixin(class {});

/**
 * @param {Record<string, any>} [overrides]
 * @returns {any}
 */
function makeSearchModel(overrides = {}) {
    const model = new FavoritesModel();
    Object.assign(
        model,
        makeCompositionDouble("search/search_favorites_mixin.js", {
            // The two the favorites mixin owns that would otherwise reach the
            // ORM; the substrate comes from the shared, contract-checked double.
            _createIrFilters: async () => 42,
            _getIrFilterDescription: () => ({
                preFavorite: { userIds: [1], domain: "[]", context: {}, orderedBy: [] },
                irFilter: { name: "My Fav", domain: "[]", context: {} },
            }),
            ...overrides,
        }),
    );
    return model;
}

describe("createNewFavorite", () => {
    test("creates a favorite item and returns serverSideId", async () => {
        const model = makeSearchModel();

        const serverSideId = await model.createNewFavorite({});

        expect(serverSideId).toBe(42);
        expect(model.searchItems[1].type).toBe("favorite");
        expect(model.searchItems[1].serverSideId).toBe(42);
    });

    test("private favorite gets FAVORITE_PRIVATE_GROUP number", async () => {
        const model = makeSearchModel();

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
        model.query = [{ searchItemId: 99 }];

        await model.createNewFavorite({});

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
