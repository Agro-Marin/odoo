// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { computeNextConfig } from "@web/model/relational_model/config_transitions";

describe.current.tags("headless");

const DEPS = { hasRoot: true };

/** @param {{ groupBy?: string[], limit?: number }} [options] */
function baseConfig({ groupBy = [], limit = 80 } = {}) {
    return {
        isMonoRecord: false,
        resModel: "thing",
        context: {},
        domain: [],
        groupBy,
        orderBy: [],
        fields: { step: { name: "step", type: "selection" } },
        activeFields: {},
        limit,
        offset: 0,
    };
}

describe("computeNextConfig limit reset across the grouped boundary", () => {
    test("ungrouped -> grouped drops the limit without a domain in params", () => {
        const next = computeNextConfig(baseConfig(), { groupBy: ["step"] }, DEPS);
        expect(next.groupBy).toEqual(["step"]);
        expect("limit" in next).toBe(false);
    });

    test("grouped -> ungrouped drops the limit without a domain in params", () => {
        const next = computeNextConfig(
            baseConfig({ groupBy: ["step"], limit: 10 }),
            { groupBy: [] },
            DEPS,
        );
        expect(next.groupBy).toEqual([]);
        expect("limit" in next).toBe(false);
    });

    test("ungrouped -> grouped drops the limit when a domain IS passed", () => {
        const next = computeNextConfig(
            baseConfig(),
            { groupBy: ["step"], domain: [["step", "=", "a"]] },
            DEPS,
        );
        expect("limit" in next).toBe(false);
    });

    test("staying grouped keeps the limit", () => {
        const next = computeNextConfig(
            baseConfig({ groupBy: ["step"], limit: 10 }),
            { groupBy: ["other"] },
            DEPS,
        );
        expect(next.limit).toBe(10);
    });

    test("staying ungrouped keeps the limit", () => {
        const next = computeNextConfig(baseConfig(), { domain: [["a", "=", 1]] }, DEPS);
        expect(next.limit).toBe(80);
    });
});
