// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { computeGroupDomain } from "@web/search/search_domain";

describe.current.tags("headless");

const FIELDS = {
    owner_id: { type: "many2one" },
    tag_ids: { type: "many2many" },
    state: { type: "selection" },
};

/**
 * @param {string} fieldName
 * @param {Array<[any, Array<[any, boolean]>]>} groupEntries
 * @param {boolean} [enableCounters=true]
 */
function makeGroupedFilter(fieldName, groupEntries, enableCounters = true) {
    return {
        fieldName,
        enableCounters,
        groups: new Map(
            groupEntries.map(([groupId, values]) => [
                groupId,
                {
                    values: new Map(
                        values.map(([id, checked]) => [id, { id, checked }]),
                    ),
                },
            ]),
        ),
    };
}

describe("counters disabled or ungrouped", () => {
    test("many2one yields a neutral domain", () => {
        expect(
            computeGroupDomain(
                { fieldName: "owner_id", enableCounters: false, groups: null },
                FIELDS,
            ),
        ).toEqual([]);
    });

    test("many2many yields a neutral per-group map", () => {
        expect(
            computeGroupDomain(
                { fieldName: "tag_ids", enableCounters: false, groups: null },
                FIELDS,
            ),
        ).toEqual({});
    });
});

describe("selection fields", () => {
    test("ungrouped selection returns null, never undefined", () => {
        const result = computeGroupDomain(
            { fieldName: "state", enableCounters: false, groups: null },
            FIELDS,
        );
        expect(result).toBe(null);
    });

    test("grouped selection with counters returns null", () => {
        const filter = makeGroupedFilter("state", [
            [1, [["abc", true]]],
            [2, [["def", false]]],
        ]);
        expect(computeGroupDomain(filter, FIELDS)).toBe(null);
    });
});

describe("many2one", () => {
    test("one active group restricts to that group's values", () => {
        const filter = makeGroupedFilter("owner_id", [
            [
                1,
                [
                    [1, true],
                    [2, false],
                ],
            ],
            [2, [[3, false]]],
        ]);
        expect(computeGroupDomain(filter, FIELDS)).toEqual([
            ["owner_id", "in", [1, 2]],
        ]);
    });

    test("two active groups are mutually exclusive, so nothing matches", () => {
        const filter = makeGroupedFilter("owner_id", [
            [1, [[1, true]]],
            [2, [[3, true]]],
        ]);
        expect(computeGroupDomain(filter, FIELDS)).toEqual([[0, "=", 1]]);
    });

    test("no active group leaves the counts alone", () => {
        const filter = makeGroupedFilter("owner_id", [
            [1, [[1, false]]],
            [2, [[3, false]]],
        ]);
        expect(computeGroupDomain(filter, FIELDS)).toBe(null);
    });
});

describe("many2many", () => {
    test("each group is complemented by the OTHER groups' checked values", () => {
        const filter = makeGroupedFilter("tag_ids", [
            [1, [[10, true]]],
            [2, [[20, true]]],
        ]);
        expect(computeGroupDomain(filter, FIELDS)).toEqual({
            1: [["tag_ids", "in", [20]]],
            2: [["tag_ids", "in", [10]]],
        });
    });
});
