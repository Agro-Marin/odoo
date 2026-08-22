// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { DynamicGroupList } from "@web/model/relational_model/dynamic_group_list";

describe.current.tags("headless");

const FIRST_DOMAIN_TOTAL = 25000;
const FIRST_DOMAIN = [["active", "=", true]];
const NARROWER_DOMAIN = [
    ["active", "=", true],
    ["step_id", "=", 3],
];

/**
 * @param {{ limit: number, searchCount: () => number }} options
 */
function makeGroupList({ limit, searchCount }) {
    const list = Object.create(DynamicGroupList.prototype);
    list.isDomainSelected = true;
    list._nbRecordsMatchingDomain = null;
    list._countedDomainKey = undefined;
    list.groups = [];
    list.count = 0;
    list._config = {
        domain: FIRST_DOMAIN,
        orderBy: [],
        groupBy: ["step_id"],
        context: {},
        resModel: "res.model",
        fields: {},
        activeFields: {},
        fieldsToAggregate: [],
        groups: {},
        limit,
    };
    list.model = {
        initialCountLimit: 10000,
        orm: { searchCount: async () => searchCount() },
    };
    list._createGroupDatapoint = (/** @type {any} */ data) => ({
        count: data.count,
        isFolded: false,
        records: /** @type {any[]} */ ([]),
        list: { _selectDomain() {} },
    });
    return list;
}

/**
 * @param {any} list
 * @param {number[]} counts
 * @param {any} [domain]
 */
function reload(list, counts, domain = list._config.domain) {
    list._config.domain = domain;
    list._setData({
        groups: counts.map((count) => ({ count })),
        length: counts.length,
    });
}

describe("DynamicGroupList record count across reloads", () => {
    test("a cached count is dropped when the same instance reloads a new domain", async () => {
        let total = FIRST_DOMAIN_TOTAL;
        const list = makeGroupList({ limit: 10, searchCount: () => total });

        reload(list, Array(12).fill(2000));
        await list._ensureCorrectRecordCount();
        expect(list.recordCount).toBe(FIRST_DOMAIN_TOTAL);

        total = 6;
        reload(list, [1, 2, 3], NARROWER_DOMAIN);
        await list._ensureCorrectRecordCount();

        expect(list.recordCount).toBe(6);
        expect(list.isRecordCountTrustable).toBe(true);
    });

    test("a still-untrustable new domain refetches instead of reusing the old count", async () => {
        let total = FIRST_DOMAIN_TOTAL;
        let calls = 0;
        const list = makeGroupList({
            limit: 2,
            searchCount: () => {
                calls++;
                return total;
            },
        });

        reload(list, [10, 10, 10]);
        await list._ensureCorrectRecordCount();
        expect(calls).toBe(1);
        expect(list.recordCount).toBe(FIRST_DOMAIN_TOTAL);

        total = 42;
        reload(list, [10, 10, 10], NARROWER_DOMAIN);
        await list._ensureCorrectRecordCount();

        expect(calls).toBe(2);
        expect(list.recordCount).toBe(42);
    });

    test("a same-domain reload keeps the cached count and issues no RPC", async () => {
        let calls = 0;
        const list = makeGroupList({
            limit: 2,
            searchCount: () => {
                calls++;
                return FIRST_DOMAIN_TOTAL;
            },
        });

        reload(list, [10, 10, 10]);
        await list._ensureCorrectRecordCount();
        expect(calls).toBe(1);

        reload(list, [10, 10, 10]);
        await list._ensureCorrectRecordCount();

        expect(calls).toBe(1);
        expect(list.recordCount).toBe(FIRST_DOMAIN_TOTAL);
    });
});
