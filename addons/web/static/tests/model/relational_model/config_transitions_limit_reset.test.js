// @ts-check

/**
 * ``computeNextConfig`` must drop ``config.limit`` when a load crosses the
 * grouped/ungrouped boundary: the number means "records per page" on a flat
 * list and "GROUPS per page" on a grouped one, and the two defaults differ
 * (``DEFAULT_LIMIT`` 80 vs ``DEFAULT_OPEN_GROUP_LIMIT`` 10 for an auto-unfolding
 * kanban). Carrying the old number over makes the list fetch the wrong page
 * size — 80 auto-unfolded groups, each pulling its own records, instead of 10.
 *
 * The reset used to live inside an ``if (params.domain)`` branch it has nothing
 * to do with, so it only fired when the caller happened to also pass a domain.
 * It usually does — ``getSearchParams`` forwards all four SEARCH_KEYS — which
 * is why this stayed latent rather than obviously broken.
 */

import { describe, expect, test } from "@odoo/hoot";
import { computeNextConfig } from "@web/model/relational_model/config_transitions";

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
