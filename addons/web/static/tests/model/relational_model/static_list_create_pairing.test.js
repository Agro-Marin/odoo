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

        expect(pairs.get("virtual_1")).toBe(10);
        expect(pairs.get("virtual_2")).toBe(11);
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

        expect(pairs.get("virtual_9")).toBe(undefined);
    });

    test("ranking is numeric, not lexicographic", () => {
        const pairs = pairedOrThrow(["a", "b", "c"], [100, 9, 20]);

        expect([pairs.get("a"), pairs.get("b"), pairs.get("c")]).toEqual([9, 20, 100]);
    });
});
