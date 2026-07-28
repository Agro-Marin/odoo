// @ts-check

/**
 * A sample-data view grouped by a PROPERTY renders instead of throwing.
 *
 * This is the case that makes ``SampleServer``'s schema and the model's
 * ``config.fields`` look like they could diverge: a property axis
 * (``properties.my_char``) exists in neither until
 * ``RelationalModel._getPropertyDefinition`` fetches it, well after the sample
 * server was constructed. They do NOT diverge — a view hands the very same
 * ``fields`` object to ``buildSampleORM`` and to the model config
 * (``extractFieldsFromArchInfo`` returns the object it was given) — so the
 * runtime-registered property is visible to the sample server as well.
 *
 * Pinned here because that aliasing is load-bearing and entirely implicit: were
 * a view ever to copy ``fields`` on its way into the model config, this test is
 * what would catch the sample server going blind to every dynamic field.
 */

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
    _records = [];
}

class Parent extends models.Model {
    _name = "parent";
    name = fields.Char();
    definitions = fields.PropertiesDefinition();
    _records = [{ id: 1, name: "P", definitions: [] }];
}

defineModels([Partner, Parent, ResCompany, ResPartner, ResUsers]);

test("a sample kanban grouped by a property renders", async () => {
    onRpc("get_property_definition", () => ({ name: "my_char", type: "char" }));
    // real groups exist but hold no records: sample mode engages and
    // redistributes generated records over them (_tweakExistingGroups)
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

    // the property axis resolved through to the sample server, which bucketed
    // its generated records over the real groups instead of throwing
    expect(".o_content").toHaveClass("o_view_sample_data");
    expect(".o_kanban_group").toHaveCount(2);
    expect(queryAll(".o_kanban_record").length > 0).toBe(true);
});
