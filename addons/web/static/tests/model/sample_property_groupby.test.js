// @ts-check

import { expect, test } from "@odoo/hoot";
import { queryAll } from "@odoo/hoot-dom";
import {
    defineModels,
    fields,
    models,
    mountView,
    onRpc,
    webModels,
} from "@web/../tests/web_test_helpers";

const { ResCompany, ResPartner, ResUsers } = webModels;

class Partner extends models.Model {
    name = fields.Char();
    properties = fields.Properties({
        definition_record: "parent_id",
        definition_record_field: "definitions",
    });
    parent_id = fields.Many2one({ relation: "parent" });
    /** @type {any[]} */
    _records = [];
}

class Parent extends models.Model {
    _name = "parent";
    name = fields.Char();
    definitions = fields.PropertiesDefinition();
    _records = [{ id: 1, name: "P", definitions: /** @type {any[]} */ ([]) }];
}

defineModels([Partner, Parent, ResCompany, ResPartner, ResUsers]);

test("a sample kanban grouped by a property renders", async () => {
    onRpc("get_property_definition", () => ({ name: "my_char", type: "char" }));
    onRpc("web_read_group", () => ({
        groups: [
            {
                "properties.my_char": "aaa",
                __extra_domain: [],
                __count: 0,
                __records: [],
            },
            {
                "properties.my_char": "bbb",
                __extra_domain: [],
                __count: 0,
                __records: [],
            },
        ],
        length: 2,
    }));

    await mountView({
        arch: `
            <kanban sample="1">
                <templates>
                    <div t-name="card"><field name="name"/></div>
                </templates>
            </kanban>`,
        resModel: "partner",
        type: "kanban",
        groupBy: ["properties.my_char"],
        domain: [["id", "<", 0]],
    });

    expect(".o_content").toHaveClass("o_view_sample_data");
    expect(".o_kanban_group").toHaveCount(2);
    expect(queryAll(".o_kanban_record").length > 0).toBe(true);
});
