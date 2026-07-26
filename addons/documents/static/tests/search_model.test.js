import { DocumentsSearchModel } from "@documents/views/search/documents_search_model";
import { describe, expect, test } from "@odoo/hoot";

/**
 * Unit tests for the folder-category bookkeeping of {@link DocumentsSearchModel}.
 *
 * Nothing is mounted and no model is instantiated: the methods under test are
 * pure functions of a `category` descriptor (`rootIds` / `values` /
 * `childrenIds`), so they are called straight off the prototype with a
 * hand-built category.
 *
 * SCOPE, stated plainly: the malformed categories below (an id in `rootIds` or
 * `childrenIds` with no `values` entry; a cyclic `childrenIds`) are NOT states
 * the running application produces. `web`'s search arch parser always seeds
 * `values[false]`, `search_panel_fetch` derives `rootIds`/`childrenIds` purely
 * from `values`, single-parent nodes put every cycle in a component with no
 * root, and the ORM rejects a folder cycle outright. These tests therefore pin
 * the *contract* of `_isCategoryValueReachable` against inputs it is not
 * currently given -- they document that it terminates and stays complete no
 * matter what `web` hands it. They are not regressions for a user-visible bug.
 */
describe.current.tags("headless");

/**
 * Build a category descriptor shaped like the one the base search panel
 * produces: `rootIds` always leads with the synthetic `false` ("All") root,
 * which has no entry in `values` unless a previous build seeded one.
 *
 * @param {Object} param0
 * @param {Array} param0.rootIds
 * @param {Object[]} param0.folders `{id, childrenIds}` entries for `values`
 * @returns {Object}
 */
function makeCategory({ rootIds, folders }) {
    return {
        rootIds,
        values: new Map(folders.map((folder) => [folder.id, folder])),
    };
}

const isReachable = (category, valueId) =>
    DocumentsSearchModel.prototype._isCategoryValueReachable.call(
        null,
        category,
        valueId,
    );

describe("_isCategoryValueReachable", () => {
    test("finds a root and a nested folder", () => {
        const category = makeCategory({
            rootIds: [false, "COMPANY"],
            folders: [
                { id: "COMPANY", childrenIds: [1] },
                { id: 1, childrenIds: [2] },
                { id: 2, childrenIds: [] },
            ],
        });

        expect(isReachable(category, "COMPANY")).toBe(true);
        expect(isReachable(category, 1)).toBe(true);
        expect(isReachable(category, 2)).toBe(true);
        expect(isReachable(category, 999)).toBe(false, {
            message: "a folder that is in no tree is not reachable",
        });
    });

    test("an unresolvable id does not abort the rest of the walk", () => {
        // "MY" is listed as a root but absent from `values`. Popping happens
        // from the END of the queue, so "MY" is visited before "COMPANY": the
        // old `while ((folder = values.get(queue.pop())))` stopped right there
        // and reported every remaining root as unreachable, which would make
        // `_ensureCategoryValue` bounce the user out of a valid folder.
        // `search_panel_fetch` does not currently emit such a category (see the
        // scope note at the top); this pins the behaviour if it ever does.
        const category = makeCategory({
            rootIds: [false, "COMPANY", "MY"],
            folders: [
                { id: "COMPANY", childrenIds: [7] },
                { id: 7, childrenIds: [] },
            ],
        });

        expect(isReachable(category, "COMPANY")).toBe(true);
        expect(isReachable(category, 7)).toBe(true, {
            message: "a folder queued behind an unresolvable root is still found",
        });
    });

    test("an unresolvable child does not abort the rest of the walk", () => {
        const category = makeCategory({
            rootIds: [false, "COMPANY"],
            // 404 has no entry in `values`, and it is queued after 5, so it is
            // popped first.
            folders: [
                { id: "COMPANY", childrenIds: [5, 404] },
                { id: 5, childrenIds: [] },
            ],
        });

        expect(isReachable(category, 5)).toBe(true);
        expect(isReachable(category, 404)).toBe(false);
    });

    test("a cyclic parent chain terminates instead of hanging", () => {
        // Without a `seen` set this walk pushes children forever and hangs the
        // tab (verified: the pre-fix implementation ran this test until the
        // browser's CDP socket timed out at 322s).
        //
        // Reachability: a real category cannot produce this, because each node
        // has exactly one `parentId`, so a cycle is an isolated component that
        // never appears in `rootIds`. The guard exists because that invariant is
        // enforced in `web`, not here, and the failure mode is a hang.
        const category = makeCategory({
            rootIds: [false, "COMPANY"],
            folders: [
                { id: "COMPANY", childrenIds: [1] },
                { id: 1, childrenIds: [2] },
                { id: 2, childrenIds: [1] },
            ],
        });

        expect(isReachable(category, 2)).toBe(true);
        expect(isReachable(category, "nope")).toBe(false, {
            message: "the walk terminates on a cycle rather than looping forever",
        });
    });

    test("no roots at all", () => {
        expect(isReachable(makeCategory({ rootIds: [], folders: [] }), 1)).toBe(false);
    });
});

describe("folderCategory", () => {
    test("resolves the folder section by field name, not by position or id", () => {
        // Section ids come from the searchpanel arch order (`nextSectionId++`),
        // so `sections.get(1)` -- what `orderBy`/`groupBy` used to do -- silently
        // reads whichever section happens to be declared first. Here a filter
        // section holds id 1 and the folder category holds id 2.
        const folderSection = {
            id: 2,
            type: "category",
            fieldName: "user_folder_id",
            activeValueId: "TRASH",
        };
        const model = Object.create(DocumentsSearchModel.prototype);
        Object.defineProperty(model, "categories", {
            value: [folderSection],
        });
        Object.defineProperty(model, "sections", {
            value: new Map([
                [1, { id: 1, type: "filter", fieldName: "tag_ids" }],
                [2, folderSection],
            ]),
        });

        expect(model.folderCategory).toBe(folderSection);
        expect(model.folderCategory.activeValueId).toBe("TRASH");
    });
});
