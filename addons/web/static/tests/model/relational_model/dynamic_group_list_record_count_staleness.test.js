// @ts-check

/**
 * ``DynamicGroupList._nbRecordsMatchingDomain`` caches the ``search_count`` of
 * ONE domain, but was not tied to that domain. Once set it was sticky for the
 * instance's lifetime, because:
 *
 *   - ``recordCount`` returns it verbatim whenever it is non-null, and
 *   - ``isRecordCountTrustable`` reports ``true`` for the same reason, so
 *     ``_ensureCorrectRecordCount`` short-circuits and never refetches.
 *
 * A reload that changes the domain ON THE SAME INSTANCE therefore kept
 * answering for the previous one, to the delete / archive truncation warnings
 * and to ``Group.applyFilter``. See
 * ``dynamic_group_list_record_count_reachability.test.js`` for which production
 * flows do and do not reuse the instance — a root search change does NOT, so
 * this guards the instance-reusing reloads (``Group.applyFilter``, and any
 * future ``list.load({domain})`` caller).
 *
 * The invalidation is keyed on the domain rather than fired on every
 * ``_setData``, so a same-domain reload (``sortBy``, the pager) does not
 * re-issue a ``search_count`` for a number already known — the last test pins
 * that.
 */

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
 * A DynamicGroupList with no model behind it: ``_createGroupDatapoint`` is
 * stubbed so ``_setData`` can run on plain group descriptors.
 *
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
 * Reload the SAME instance, the way ``_reloadWithConfig`` does: commit the new
 * config first, then hand the fresh payload to ``_setData``.
 *
 * @param {any} list
 * @param {number[]} counts one group count per group
 * @param {any} [domain] the reloaded domain (defaults to unchanged)
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

        // First search: 12 groups > limit 10, so the summed group counts cannot
        // be trusted and the model falls back to a search_count.
        reload(list, Array(12).fill(2000));
        await list._ensureCorrectRecordCount();
        expect(list.recordCount).toBe(FIRST_DOMAIN_TOTAL);

        // Narrower domain on the same instance: 3 groups, 6 records. The summed
        // group counts are now authoritative (3 groups <= limit 10).
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

        // ``sortBy`` / the pager reload the same instance under the same domain.
        reload(list, [10, 10, 10]);
        await list._ensureCorrectRecordCount();

        expect(calls).toBe(1);
        expect(list.recordCount).toBe(FIRST_DOMAIN_TOTAL);
    });
});
