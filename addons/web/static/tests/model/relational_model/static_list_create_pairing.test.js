// @ts-check

/**
 * `pairCreatedRows` is the single source of the virtualId -> resId mapping used
 * both by `_commitSave` (to rekey the cache) and by `resolveCreatedResId`
 * (to open a freshly created row in a dialog). The two used to carry separate
 * copies of the heuristic, so these pin the shared contract.
 */

import { describe, expect, test } from "@odoo/hoot";
import { pairCreatedRows } from "@web/model/relational_model/static_list_utils";

describe.current.tags("headless");

/**
 * `pairCreatedRows` answers null when the two batches disagree in size, which
 * every test below but one considers a failure -- so say that once, here,
 * rather than let each caller read through a null.
 *
 * @param {string[]} virtualIds
 * @param {number[]} newIds
 * @returns {Map<string | number, number>}
 */
function pairedOrThrow(virtualIds, newIds) {
    const pairs = pairCreatedRows(virtualIds, newIds);
    if (!pairs) {
        throw new Error(
            `pairCreatedRows(${JSON.stringify(virtualIds)}, ${JSON.stringify(newIds)}) returned null`,
        );
    }
    return pairs;
}

describe("pairCreatedRows", () => {
    test("zips virtual ids against new ids in creation order", () => {
        const pairs = pairedOrThrow(["virtual_1", "virtual_2"], [11, 10]);

        expect(/** @type {Map<string, number>} */ (pairs).get("virtual_1")).toBe(10);
        expect(/** @type {Map<string, number>} */ (pairs).get("virtual_2")).toBe(11);
    });

    test("returns null when the counts disagree", () => {
        expect(pairCreatedRows(["virtual_1", "virtual_2"], [10])).toBe(null);
        expect(pairCreatedRows(["virtual_1"], [10, 11])).toBe(null);
    });

    test("an empty batch pairs nothing rather than failing", () => {
        const pairs = pairedOrThrow([], []);

        expect(pairs.size).toBe(0);
    });

    test("an unknown virtual id has no pairing", () => {
        const pairs = pairedOrThrow(["virtual_1"], [10]);

        expect(/** @type {Map<string, number>} */ (pairs).get("virtual_9")).toBe(
            undefined,
        );
    });

    test("ranking is numeric, not lexicographic", () => {
        const pairs = pairedOrThrow(["a", "b", "c"], [100, 9, 20]);

        expect([pairs.get("a"), pairs.get("b"), pairs.get("c")]).toEqual([9, 20, 100]);
    });
});

describe("pairCreatedRows positional identity", () => {
    test("a bottom create pairs when the new id sits where the row was", () => {
        const pairs = pairCreatedRows(["virtual_1"], [90], {
            clientIds: [2, 3, "virtual_1"],
            serverIds: [2, 3, 90],
        });

        expect(pairs).not.toBe(null);
        expect(/** @type {Map<string, number>} */ (pairs).get("virtual_1")).toBe(90);
    });

    test("a multi-row create pairs each row at its own position", () => {
        const pairs = pairCreatedRows(["virtual_1", "virtual_2"], [91, 90], {
            clientIds: [2, "virtual_1", "virtual_2"],
            serverIds: [2, 90, 91],
        });

        expect(pairs).not.toBe(null);
        expect(/** @type {Map<string, number>} */ (pairs).get("virtual_1")).toBe(90);
        expect(/** @type {Map<string, number>} */ (pairs).get("virtual_2")).toBe(91);
    });

    test("a foreign new id at a different position is refused", () => {
        // The server dropped our created row and inserted one of its own: the
        // counts agree (one create, one new id), but the new id does not sit
        // where our row was. Zipping here would graft our edited datapoint
        // onto a record we never created.
        const pairs = pairCreatedRows(["virtual_1"], [999], {
            clientIds: [2, "virtual_1", 3],
            serverIds: [2, 3, 999],
        });

        expect(pairs).toBe(null);
    });

    test("a virtual id absent from the client membership is refused", () => {
        const pairs = pairCreatedRows(["virtual_1"], [90], {
            clientIds: [2, 3],
            serverIds: [2, 3, 90],
        });

        expect(pairs).toBe(null);
    });

    test("without positions the rank-order zip is unchanged", () => {
        const pairs = pairedOrThrow(["virtual_1"], [999]);

        expect(/** @type {Map<string, number>} */ (pairs).get("virtual_1")).toBe(999);
    });
});
