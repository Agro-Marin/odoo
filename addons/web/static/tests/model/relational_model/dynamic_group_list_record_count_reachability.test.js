// @ts-check

/**
 * REACHABILITY PROBE for the ``_nbRecordsMatchingDomain`` staleness fixed in
 * ``dynamic_group_list.js``. Runs the real view stack rather than driving
 * ``_setData`` on a bare prototype, to answer one question honestly: which
 * production flow actually reuses a DynamicGroupList across a domain change?
 *
 * These tests assert what the stack DOES (they pass either way); they exist to
 * document the blast radius, not to guard the fix.
 */

import { beforeEach, describe, expect, test } from "@odoo/hoot";
import {
    defineModels,
    fields,
    models,
    mountView,
    patchWithCleanup,
    webModels,
} from "@web/../tests/web_test_helpers";
import { ListController } from "@web/views/list/list_controller";

class Thing extends models.Model {
    _name = "thing";
    name = fields.Char();
    step = fields.Selection({
        selection: [
            ["a", "A"],
            ["b", "B"],
            ["c", "C"],
        ],
    });
    /** @type {any[]} */
    _records = [];
}

defineModels({ ...webModels, Thing });

beforeEach(() => {
    Thing._records = Array.from({ length: 30 }, (_, i) => ({
        id: i + 1,
        name: `t${i + 1}`,
        step: ["a", "b", "c"][i % 3],
    }));
});

/** Mount a grouped list and hand back the live RelationalModel. */
async function mountGrouped() {
    /** @type {any} */
    let model;
    patchWithCleanup(ListController.prototype, {
        setup() {
            super.setup(...arguments);
            model = /** @type {any} */ (this).model;
        },
    });
    await mountView({
        type: "list",
        resModel: "thing",
        arch: `<list groups_limit="2"><field name="name"/></list>`,
        groupBy: ["step"],
    });
    return model;
}

describe("_nbRecordsMatchingDomain reachability", () => {
    test("a root search-domain change builds a NEW list instance", async () => {
        const model = await mountGrouped();
        const firstRoot = model.root;

        await model.root.selectDomain(true);
        expect(firstRoot._nbRecordsMatchingDomain).toBe(30);

        await model.load({ domain: [["step", "=", "a"]] });

        // The root is rebuilt from scratch by ``load``, so the cached count
        // cannot leak across a search change on the ROOT list.
        expect(model.root).not.toBe(firstRoot);
        expect(model.root._nbRecordsMatchingDomain).toBe(null);
    });

    test("reloading the SAME instance is what carries state across", async () => {
        const model = await mountGrouped();
        const root = model.root;

        await root.selectDomain(true);
        expect(root._nbRecordsMatchingDomain).toBe(30);

        // ``sortBy`` / pager / ``Group.applyFilter`` all go through the
        // instance-reusing ``_load``, unlike ``model.load``. Only these can
        // carry a cached count across a reload — which is why the invalidation
        // lives in ``_setData`` and is keyed on the domain.
        await root.sortBy("step");
        expect(model.root).toBe(root);

        // Same domain, so the cached count is deliberately KEPT: no redundant
        // search_count for a number already known.
        expect(root._nbRecordsMatchingDomain).toBe(30);
    });
});
