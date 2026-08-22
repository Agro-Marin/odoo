// @ts-check

import { expect, test } from "@odoo/hoot";
import { queryAllTexts } from "@odoo/hoot-dom";
import {
    defineModels,
    fields,
    MockServer,
    models,
    mountView,
    onRpc,
    patchWithCleanup,
    webModels,
} from "@web/../tests/web_test_helpers";
import { KanbanController } from "@web/views/kanban/kanban_controller";

class Product extends models.Model {
    name = fields.Char();
    _records = [1, 2, 3, 4, 5, 6].map((id) => ({ id, name: `P${id}` }));
}

class Task extends models.Model {
    name = fields.Char();
    product_id = fields.Many2one({ relation: "product" });
    _records = [1, 2, 3, 4, 5, 6].map((id) => ({
        id,
        name: `task${id}`,
        product_id: id,
    }));
}

defineModels({ ...webModels, Product, Task });

test("grouped kanban keeps column order after three columns empty out", async () => {
    /** @type {any} */
    let model;
    patchWithCleanup(KanbanController.prototype, {
        setup() {
            super.setup();
            model = /** @type {any} */ (this).model;
        },
    });

    await mountView({
        type: "kanban",
        resModel: "task",
        arch: `<kanban><templates><t t-name="card"><field name="name"/></t></templates></kanban>`,
        groupBy: ["product_id"],
    });

    expect(model.root.groups.map((/** @type {any} */ g) => g.value)).toEqual([
        1, 2, 3, 4, 5, 6,
    ]);

    MockServer.env["task"].unlink([2, 4, 6]);
    onRpc("task", "web_read_group", ({ parent }) => {
        const res = parent();
        expect.step(
            "server groups: " +
                JSON.stringify(
                    res.groups.map(
                        (/** @type {any} */ g) => g.product_id && g.product_id[0],
                    ),
                ),
        );
        return res;
    });
    await model.load();
    expect.step(
        "after reload: " +
            JSON.stringify(model.root.groups.map((/** @type {any} */ g) => g.value)),
    );

    expect.verifySteps(["server groups: [1,3,5]", "after reload: [1,2,3,4,5,6]"]);
    const columns = queryAllTexts(".o_column_title").map((t) =>
        t.trim().split("\n")[0].trim(),
    );
    expect(columns).toEqual(["P1", "P2", "P3", "P4", "P5", "P6"]);
});
