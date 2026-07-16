import { defineMailModels } from "@mail/../tests/mail_test_helpers";
import { expect, test } from "@odoo/hoot";
import { animationFrame, queryAll } from "@odoo/hoot-dom";
import {
    contains,
    defineModels,
    fields,
    MockServer,
    models,
    mountView,
    onRpc,
} from "@web/../tests/web_test_helpers";
import { luxon } from "@web/core/l10n/luxon";

const { DateTime } = luxon;

const arch = `
    <list editable="top" js_class="inventory_report_list">
        <field name="name"/>
        <field name="age"/>
        <field name="job"/>
        <field name="create_date" invisible="1"/>
        <field name="write_date" invisible="1"/>
    </list>
`;

const setup_date = "2022-01-03 08:03:44";

onRpc("person", "web_save", ({ args }) => {
    // simulate 'stock.quant' create function which can return existing record
    const values = args[1];
    const existingRecord = MockServer.env.person.find((p) => p.name === values.name);
    if (existingRecord) {
        values.create_date = existingRecord.create_date;
        values.write_date = DateTime.now().toSQL();
        return [Object.assign(existingRecord, values)];
    }
});

class Person extends models.Model {
    name = fields.Char();
    age = fields.Integer();
    job = fields.Char({ string: "Profession" });
    create_date = fields.Datetime({ string: "Created on" });
    write_date = fields.Datetime({ string: "Last Updated on" });

    _records = [
        {
            id: 1,
            name: "Daniel Fortesque",
            age: 32,
            job: "Soldier",
            create_date: setup_date,
            write_date: setup_date,
        },
        {
            id: 2,
            name: "Samuel Oak",
            age: 64,
            job: "Professor",
            create_date: setup_date,
            write_date: setup_date,
        },
        {
            id: 3,
            name: "Leto II Atreides",
            age: 128,
            job: "Emperor",
            create_date: setup_date,
            write_date: setup_date,
        },
    ];
}

defineModels([Person]);
defineMailModels();

test("Create new record correctly", async function () {
    await mountView({
        type: "list",
        resModel: "person",
        arch,
        context: {
            inventory_mode: true,
        },
    });

    // Check we have initially 3 records
    expect(".o_data_row").toHaveCount(3);

    // Create a new line...
    await contains(".o_control_panel_main_buttons .o_list_button_add").click();
    await contains("[name=name] input").edit("Bilou", { confirm: false });
    await contains("[name=age] input").edit("24", { confirm: false });
    await contains(".o_control_panel_main_buttons .o_list_button_save").click();

    // Check new record is in the list
    expect(".o_data_row").toHaveCount(4);
});

test("Don't duplicate record", async function () {
    await mountView({
        type: "list",
        resModel: "person",
        arch,
        context: {
            inventory_mode: true,
        },
    });

    // Check we have initially 3 records
    expect(".o_data_row").toHaveCount(3);

    // Create a new line for an existing record...
    await contains(".o_control_panel_main_buttons .o_list_button_add").click();
    await contains("[name=name] input").edit("Leto II Atreides", { confirm: false });
    await contains("[name=age] input").edit("72", { confirm: false });
    await contains(".o_control_panel_main_buttons .o_list_button_save").click();

    expect(".o_data_row").toHaveCount(3, { message: "should still have 3 records" });
    expect(".o_data_row:eq(2) .o_list_number").toHaveText("72", {
        message: "The age field must be updated",
    });
    await animationFrame();
    expect(".o_notification").toHaveCount(1);
    expect(".o_notification .o_notification_body").toHaveText(
        "This record already exists. You tried to create a record that already exists. The existing record was modified instead.",
    );
});

test("Work in grouped list", async function () {
    await mountView({
        type: "list",
        resModel: "person",
        arch,
        context: {
            inventory_mode: true,
        },
        groupBy: ["job"], // Groups are Emperor, Professor, Soldier
    });

    // Open 'Professor' group
    await contains(".o_group_header:eq(1)").click();

    // Check we have only 1 record...
    expect(".o_data_row").toHaveCount(1);

    // Create a new record...
    await contains(".o_group_field_row_add a").click();
    await contains("[name=name] input").edit("Del Tutorial", { confirm: false });
    await contains("[name=age] input").edit("32", { confirm: false });
    await contains(".o_control_panel_main_buttons .o_list_button_save").click();
    // Check we have 2 records...
    expect(".o_data_row").toHaveCount(2);

    // Create an existing record...
    await contains(".o_group_field_row_add a").click();
    await contains("[name=name] input").edit("Samuel Oak", { confirm: false });
    await contains("[name=age] input").edit("55", { confirm: false });
    await contains(".o_control_panel_main_buttons .o_list_button_save").click();
    // Check we still have 2 records...
    expect(".o_data_row").toHaveCount(2);

    // Add an already-existing record whose group ('Soldier') is folded, so its
    // duplicate is not loaded, and whose group-by value differs from the group it
    // is added in. It must NOT be stranded in the Professor group: it is really an
    // update of the existing record, so the added row is removed.
    await contains(".o_group_field_row_add a").click();
    await contains("[name=name] input").edit("Daniel Fortesque", { confirm: false });
    await contains("[name=age] input").edit("55", { confirm: false });
    await contains("[name=job] input").edit("Soldier", { confirm: false });
    await contains(".o_control_panel_main_buttons .o_list_button_save").click();
    // The Professor group still shows only its own 2 records — no phantom Soldier
    // record left behind (which previously corrupted row indexing / spawned an
    // empty edit row).
    expect(".o_data_row").toHaveCount(2);

    // Open 'Soldier': the existing record shows in its correct group with the
    // updated value (age 55).
    await contains(".o_group_header:eq(2)").click();
    expect(".o_data_row").toHaveCount(3);
    const danielRow = queryAll(".o_data_row").find((row) =>
        row.textContent.includes("Daniel Fortesque"),
    );
    expect(danielRow.querySelector('[name="age"]').textContent).toBe("55");
});
