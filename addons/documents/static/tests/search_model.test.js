import { DocumentsSearchModel } from "@documents/views/search/documents_search_model";
import { describe, expect, test } from "@odoo/hoot";

describe.current.tags("headless");

/**
 * @param {Object} param0
 * @param {Array} param0.rootIds
 * @param {Object[]} param0.folders
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
            folders: [
                { id: "COMPANY", childrenIds: [5, 404] },
                { id: 5, childrenIds: [] },
            ],
        });

        expect(isReachable(category, 5)).toBe(true);
        expect(isReachable(category, 404)).toBe(false);
    });

    test("a cyclic parent chain terminates instead of hanging", () => {
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
