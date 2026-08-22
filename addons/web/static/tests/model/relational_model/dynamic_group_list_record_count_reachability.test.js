// @ts-check

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

        expect(model.root).not.toBe(firstRoot);
        expect(model.root._nbRecordsMatchingDomain).toBe(null);
    });

    test("reloading the SAME instance is what carries state across", async () => {
        const model = await mountGrouped();
        const root = model.root;

        await root.selectDomain(true);
        expect(root._nbRecordsMatchingDomain).toBe(30);

        await root.sortBy("step");
        expect(model.root).toBe(root);

        expect(root._nbRecordsMatchingDomain).toBe(30);
    });
});
