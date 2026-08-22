// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { makeStaticListDouble } from "@web/../tests/model/relational_model/static_list_doubles";

describe.current.tags("headless");

/**
 * @param {string} datapointId
 * @param {number | string} resId
 * @returns {any}
 */
function row(datapointId, resId) {
    return { id: datapointId, resId, _virtualId: false };
}

describe("_extendedRecords never outlives the datapoints it names", () => {
    test("a marker whose datapoint left the cache is dropped", () => {
        const list = makeStaticListDouble({ _currentIds: [7] });
        const first = row("datapoint_A", 7);
        list._cache.set(7, first);
        list._extendedRecords.add(first.id);

        list._commitCurrentIds([]);
        list.model._patchConfig(list.config, { resIds: [] });
        list._pruneCache();

        expect([...list._cache.keys()]).toEqual([]);
        expect([...list._extendedRecords]).toEqual([]);
    });

    test("a marker orphaned by a REPLACEMENT under the same key is dropped too", () => {
        const list = makeStaticListDouble({ _currentIds: [7] });
        list._cache.set(7, row("datapoint_A", 7));
        list._extendedRecords.add("datapoint_A");

        list._cache.set(7, row("datapoint_B", 7));
        list._extendedRecords.add("datapoint_B");

        list._pruneCache();

        expect([...list._cache.keys()]).toEqual([7], {
            message: "the row is still a member, so its slot must survive",
        });
        expect([...list._extendedRecords]).toEqual(["datapoint_B"], {
            message: "only the datapoint that still occupies the slot is marked",
        });
    });

    test("markers for live datapoints survive a prune that evicts others", () => {
        const list = makeStaticListDouble({ _currentIds: [1] });
        list._cache.set(1, row("dp1", 1));
        list._cache.set(2, row("dp2", 2));
        list._extendedRecords.add("dp1");
        list._extendedRecords.add("dp2");

        list._pruneCache();

        expect([...list._cache.keys()]).toEqual([1]);
        expect([...list._extendedRecords]).toEqual(["dp1"]);
    });
});

describe("_cache keys are the real ids, not their string forms", () => {
    test("a numeric resId is not reachable under its string form", () => {
        const list = makeStaticListDouble({ _currentIds: [7] });
        list._cache.set(7, row("dp7", 7));

        expect(list.getCachedRecord(7)).toEqual(row("dp7", 7));
        expect(list.getCachedRecord(/** @type {any} */ ("7"))).toBe(undefined);
    });

    test("a prune keeps numeric and virtual members alike, with no coercion", () => {
        const list = makeStaticListDouble({ _currentIds: [7, "virtual_3"] });
        list._cache.set(7, row("dp7", 7));
        list._cache.set("virtual_3", {
            id: "dpv",
            resId: false,
            _virtualId: "virtual_3",
        });
        list.model._patchConfig(list.config, { resIds: [7] });

        list._pruneCache();

        expect([...list._cache.keys()]).toEqual([7, "virtual_3"]);
    });
});
