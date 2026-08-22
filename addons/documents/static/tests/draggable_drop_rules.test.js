import { dropRejectionReason } from "@documents/views/helper/documents_draggable";
import { describe, expect, test } from "@odoo/hoot";

describe.current.tags("headless");

/**
 * @param {Object} [param0]
 * @param {number[]} [param0.movable]
 * @param {number[]} [param0.nonMovable]
 * @returns {Object}
 */
function makeCtx({ movable = [1], nonMovable = [] } = {}) {
    return {
        draggedRecords: {
            movableRecordIds: movable,
            nonMovableRecordIds: nonMovable,
            all: [...movable, ...nonMovable],
        },
    };
}

const reject = (
    targetFolder,
    { ctx = makeCtx(), isDocumentManager = false, ancestors = [] } = {},
) =>
    dropRejectionReason({
        draggedRecords: ctx.draggedRecords,
        targetFolder,
        userIsDocumentManager: isDocumentManager,
        getFolderAndParents: () => ancestors,
    });

describe("_dropRejectionReason", () => {
    test("accepts a writable real folder", () => {
        expect(reject({ id: 42, user_permission: "edit" })).toBe("");
    });

    test("rejects a real folder the user may only view", () => {
        expect(reject({ id: 42, user_permission: "view" })).not.toBe("");
    });

    test("rejects a real folder with no permission at all", () => {
        expect(reject({ id: 42, user_permission: "none" })).not.toBe("");
    });

    test("rejects the special read-only roots and a missing target", () => {
        expect(reject({ id: "RECENT" })).not.toBe("");
        expect(reject({ id: "SHARED" })).not.toBe("");
        expect(reject(false)).not.toBe("", {
            message: "a drop on a non-folder card resolves to false",
        });
    });

    test("COMPANY keeps its documents-manager exemption", () => {
        expect(reject({ id: "COMPANY", user_permission: "view" })).not.toBe("");
        expect(
            reject(
                { id: "COMPANY", user_permission: "view" },
                { isDocumentManager: true },
            ),
        ).toBe("");
        expect(reject({ id: "COMPANY", user_permission: "edit" })).toBe("");
    });

    test("MY is not permission-checked as a real folder", () => {
        expect(reject({ id: "MY" })).toBe("");
    });

    test("rejects trashing a selection holding an immovable document", () => {
        const ctx = makeCtx({ movable: [1], nonMovable: [2] });
        expect(reject({ id: "TRASH" }, { ctx })).not.toBe("");
        expect(reject({ id: "TRASH" }, { ctx: makeCtx() })).toBe("");
    });

    test("rejects dropping a folder into itself or a descendant", () => {
        const ancestors = [{ id: 7 }, { id: 1 }, { id: "COMPANY" }];
        expect(reject({ id: 7, user_permission: "edit" }, { ancestors })).not.toBe("", {
            message: "dragged folder 1 is an ancestor of the target",
        });
        expect(
            reject(
                { id: 7, user_permission: "edit" },
                { ancestors: [{ id: 7 }, { id: "COMPANY" }] },
            ),
        ).toBe("");
    });
});
