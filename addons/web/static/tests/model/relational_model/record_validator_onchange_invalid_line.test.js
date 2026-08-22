// @ts-check

import { expect, test } from "@odoo/hoot";
import { click, queryOne } from "@odoo/hoot-dom";
import {
    defineModels,
    fields,
    models,
    mountView,
    onRpc,
    webModels,
} from "@web/../tests/web_test_helpers";

class Line extends models.Model {
    name = fields.Char();
    task_id = fields.Many2one({ relation: "task" });
    _records = [{ id: 1, name: "line one", task_id: 1 }];
}

class Task extends models.Model {
    name = fields.Char();
    line_ids = fields.One2many({ relation: "line", relation_field: "task_id" });
    _records = [{ id: 1, name: "task", line_ids: [1] }];
}

defineModels({ ...webModels, Line, Task });

test("a required o2m line field cleared by an onchange blocks the save", async () => {
    onRpc("task", "onchange", () => ({
        value: { line_ids: [[1, 1, { name: false }]] },
    }));
    onRpc("task", "web_save", () => {
        expect.step("web_save");
        throw new Error("server refuses: line name is required");
    });

    await mountView({
        type: "form",
        resModel: "task",
        resId: 1,
        arch: `
            <form>
                <field name="name" on_change="1"/>
                <field name="line_ids">
                    <list editable="bottom">
                        <field name="name" required="1"/>
                    </list>
                </field>
            </form>`,
    });

    const input = /** @type {HTMLInputElement} */ (
        queryOne(".o_field_widget[name=name] input")
    );
    input.value = "changed";
    input.dispatchEvent(new InputEvent("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
    await new Promise((resolve) => setTimeout(resolve, 50));

    expect(".o_data_cell").toHaveCount(1);

    await click(".o_form_button_save");
    await new Promise((resolve) => setTimeout(resolve, 50));

    expect.verifySteps([]);
});
