// @ts-check

import { expect, test } from "@odoo/hoot";
import { queryAllTexts } from "@odoo/hoot-dom";
import {
    contains,
    defineModels,
    fields,
    models,
    mountView,
    onRpc,
} from "@web/../tests/web_test_helpers";

class Partner extends models.Model {
    name = fields.Char();
    int_field = fields.Integer();
    p = fields.One2many({ relation: "line", relation_field: "parent_id" });

    _records = [{ id: 1, int_field: 0, p: [11, 12, 13, 14] }];
}

class Line extends models.Model {
    name = fields.Char();
    parent_id = fields.Many2one({ relation: "partner" });

    _records = [
        { id: 11, name: "line 1" },
        { id: 12, name: "line 2" },
        { id: 13, name: "line 3" },
        { id: 14, name: "line 4" },
    ];
}

defineModels([Partner, Line]);

const ARCH = `
    <form>
        <field name="int_field"/>
        <field name="p">
            <list limit="2"><field name="name"/></list>
        </field>
    </form>`;

test.tags("desktop");
test("an onchange shortening the relation while on page 2 does not blank the list", async () => {
    Partner._onChanges = { int_field: () => {} };
    onRpc("onchange", () => ({
        value: {
            p: [
                [2, 13, false],
                [2, 14, false],
            ],
        },
    }));

    await mountView({ type: "form", resModel: "partner", arch: ARCH, resId: 1 });
    expect(".o_field_widget[name=p] .o_data_row").toHaveCount(2);
    expect(".o_x2m_control_panel .o_pager_counter").toHaveText("1-2 / 4");

    await contains(".o_field_widget[name=p] .o_pager_next").click();
    expect(queryAllTexts(".o_field_widget[name=p] .o_data_cell")).toEqual([
        "line 3",
        "line 4",
    ]);
    expect(".o_x2m_control_panel .o_pager_counter").toHaveText("3-4 / 4");

    await contains(".o_field_widget[name=int_field] input").edit("64");

    expect(".o_field_widget[name=p] .o_data_row").toHaveCount(2);
    expect(queryAllTexts(".o_field_widget[name=p] .o_data_cell")).toEqual([
        "line 1",
        "line 2",
    ]);
});

test("deleting the last row of the last page falls back to the previous page", async () => {
    Partner._records = [{ id: 1, int_field: 0, p: [11, 12, 13] }];

    await mountView({
        type: "form",
        resModel: "partner",
        arch: `
            <form>
                <field name="p">
                    <list limit="2" editable="bottom">
                        <field name="name"/>
                    </list>
                </field>
            </form>`,
        resId: 1,
    });

    await contains(".o_field_widget[name=p] .o_pager_next").click();
    expect(queryAllTexts(".o_field_widget[name=p] .o_data_cell")).toEqual(["line 3"]);

    await contains(".o_field_widget[name=p] .o_data_row .o_list_record_remove").click();

    expect(".o_field_widget[name=p] .o_data_row").toHaveCount(2);
    expect(queryAllTexts(".o_field_widget[name=p] .o_data_cell")).toEqual([
        "line 1",
        "line 2",
    ]);
});
