// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import {
    makeStaticListConfig,
    makeStaticListDouble,
} from "@web/../tests/model/relational_model/static_list_doubles";
import { StaticList } from "@web/model/relational_model/static_list";

describe.current.tags("headless");

/**
 * @returns {string[]}
 */
function realSetupKeys() {
    const list = Object.create(StaticList.prototype);
    const config = makeStaticListConfig();
    Object.assign(list, {
        _config: config,
        model: {
            _patchConfig: () => {},
            /** @returns {Promise<any[]>} */
            _loadRecords: async () => [],
        },
    });
    StaticList.prototype.setup.call(list, config, [], {});
    return Object.keys(list)
        .filter((key) => key !== "model" && key !== "_config")
        .sort();
}

describe("makeStaticListDouble models what StaticList.setup installs", () => {
    test("the double carries every own property setup() installs", () => {
        const missing = realSetupKeys().filter(
            (key) => !Object.hasOwn(makeStaticListDouble(), key),
        );
        expect(missing).toEqual([], {
            message:
                "StaticList.setup() gained an own property the double does not " +
                "model -- add it to makeStaticListDouble, or every test built " +
                "on the double runs with it undefined",
        });
    });

    test("the double invents no own property the class does not install", () => {
        const real = new Set(realSetupKeys());
        const invented = Object.keys(makeStaticListDouble()).filter(
            (key) => key !== "model" && key !== "_config" && !real.has(key),
        );
        expect(invented).toEqual([], {
            message:
                "the double declares state StaticList does not own -- most " +
                "likely shadowing a prototype accessor with a data property",
        });
    });

    test("records / _currentIds / _tmpIncreaseLimit stay accessors over ListMembership", () => {
        const list = makeStaticListDouble({
            _currentIds: [1, 2],
            records: [{ resId: 1 }, { resId: 2 }],
            _tmpIncreaseLimit: 3,
        });
        for (const key of ["records", "_currentIds", "_tmpIncreaseLimit"]) {
            expect(Object.hasOwn(list, key)).toBe(false, {
                message: `${key} must reach _membership, not shadow it`,
            });
        }
        expect(list._membership.ids).toEqual([1, 2]);
        expect(list._membership.records.length).toBe(2);
        expect(list._membership.tmpIncreaseLimit).toBe(3);
    });

    test("_cache is a Map keyed by the real id, not a stringifying object", () => {
        const list = makeStaticListDouble();
        list._cache.set(7, { resId: 7 });
        expect(list._cache).toBeInstanceOf(Map);
        expect(list._cache.get(7)).toEqual({ resId: 7 });
        expect(list._cache.get("7")).toBe(undefined, {
            message: "a numeric resId must not be reachable under its string form",
        });
    });
});
