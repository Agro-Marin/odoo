// @ts-check

import { expect, test } from "@odoo/hoot";
import { queryAllTexts } from "@odoo/hoot-dom";
import { runAllTimers } from "@odoo/hoot-mock";
import {
    clickSave,
    contains,
    defineModels,
    fields,
    models,
    mountView,
    onRpc,
} from "@web/../tests/web_test_helpers";

class Partner extends models.Model {
    int_field = fields.Integer({ sortable: true });
    timmy = fields.Many2many({ string: "pokemon", relation: "partner.type" });
    p = fields.One2many({
        string: "one2many field",
        relation: "partner",
        relation_field: "trululu",
    });
    trululu = fields.Many2one({ relation: "partner" });
    _records = [{ id: 1, int_field: 10, p: [1] }];
}

class PartnerType extends models.Model {
    name = fields.Char();
    _records = [
        { id: 12, name: "gold" },
        { id: 14, name: "silver" },
    ];
}

defineModels([Partner, PartnerType]);

test("Many2ManyCheckBoxesField", async () => {
    Partner._records[0].timmy = [12];
    const commands = [[[4, 14, false]], [[3, 12, false]]];
    onRpc("web_save", (args) => {
        expect.step("web_save");
        expect(args.args[1].timmy).toEqual(commands.shift());
    });
    await mountView({
        type: "form",
        resModel: "partner",
        resId: 1,
        arch: `
            <form>
                <group>
                    <field name="timmy" widget="many2many_checkboxes" />
                </group>
            </form>`,
    });

    expect("div.o_field_widget div.form-check").toHaveCount(2);

    expect("div.o_field_widget div.form-check input:eq(0)").toBeChecked();
    expect("div.o_field_widget div.form-check input:eq(1)").not.toBeChecked();

    expect("div.o_field_widget div.form-check input:disabled").toHaveCount(0);

    await contains("div.o_field_widget div.form-check input:eq(1)").click();
    await runAllTimers();
    await clickSave();
    expect("div.o_field_widget div.form-check input:checked").toHaveCount(2);

    await contains("div.o_field_widget div.form-check > label").click();
    await runAllTimers();
    await clickSave();
    expect("div.o_field_widget div.form-check input:eq(0)").not.toBeChecked();
    expect("div.o_field_widget div.form-check input:eq(1)").toBeChecked();

    expect.verifySteps(["web_save", "web_save"]);
});

test("Many2ManyCheckBoxesField (readonly)", async () => {
    Partner._records[0].timmy = [12];
    await mountView({
        type: "form",
        resModel: "partner",
        resId: 1,
        arch: `
            <form>
                <group>
                    <field name="timmy" widget="many2many_checkboxes" readonly="True" />
                </group>
            </form>`,
    });

    expect("div.o_field_widget div.form-check").toHaveCount(2, {
        message: "should have fetched and displayed the 2 values of the many2many",
    });
    expect("div.o_field_widget div.form-check input:disabled").toHaveCount(2, {
        message: "the checkboxes should be disabled",
    });

    await contains("div.o_field_widget div.form-check > label:eq(1)").click();

    expect("div.o_field_widget div.form-check input:eq(0)").toBeChecked();
    expect("div.o_field_widget div.form-check input:eq(1)").not.toBeChecked();
});

test("Many2ManyCheckBoxesField does not read added record", async () => {
    Partner._records[0].timmy = [];
    onRpc((args) => {
        expect.step(args.method);
    });
    await mountView({
        type: "form",
        resModel: "partner",
        resId: 1,
        arch: `
            <form>
                <group>
                    <field name="timmy" widget="many2many_checkboxes" />
                </group>
            </form>`,
    });

    expect("div.o_field_widget div.form-check").toHaveCount(2);
    expect(queryAllTexts(".o_field_widget .form-check-label")).toEqual([
        "gold",
        "silver",
    ]);
    expect("div.o_field_widget div.form-check input:checked").toHaveCount(0);

    await contains("div.o_field_widget div.form-check input").click();
    await runAllTimers();
    expect("div.o_field_widget div.form-check").toHaveCount(2);
    expect(queryAllTexts(".o_field_widget .form-check-label")).toEqual([
        "gold",
        "silver",
    ]);
    expect("div.o_field_widget div.form-check input:checked").toHaveCount(1);

    await clickSave();
    expect("div.o_field_widget div.form-check").toHaveCount(2);
    expect(queryAllTexts(".o_field_widget .form-check-label")).toEqual([
        "gold",
        "silver",
    ]);
    expect("div.o_field_widget div.form-check input:checked").toHaveCount(1);

    expect.verifySteps(["get_views", "web_read", "name_search", "web_save"]);
});

test("Many2ManyCheckBoxesField: start non empty, then remove twice", async () => {
    Partner._records[0].timmy = [12, 14];
    await mountView({
        type: "form",
        resModel: "partner",
        resId: 1,
        arch: `
                <form>
                    <group>
                        <field name="timmy" widget="many2many_checkboxes" />
                    </group>
                </form>`,
    });

    await contains("div.o_field_widget div.form-check input:eq(0)").click();
    await contains("div.o_field_widget div.form-check input:eq(1)").click();
    await runAllTimers();
    await clickSave();
    expect("div.o_field_widget div.form-check input:eq(0)").not.toBeChecked();
    expect("div.o_field_widget div.form-check input:eq(1)").not.toBeChecked();
});

test("Many2ManyCheckBoxesField: many2many read, field context is properly sent", async () => {
    onRpc((args) => {
        expect.step(args.method);
        if (args.method === "web_read") {
            expect(args.kwargs.specification.timmy.context).toEqual({ hello: "world" });
        } else if (args.method === "name_search") {
            expect(args.kwargs.context.hello).toEqual("world");
        }
    });
    await mountView({
        type: "form",
        resModel: "partner",
        resId: 1,
        arch: `
            <form>
                <field name="timmy" widget="many2many_checkboxes" context="{ 'hello': 'world' }" />
            </form>`,
    });
    expect.verifySteps(["get_views", "web_read", "name_search"]);
});

test("Many2ManyCheckBoxesField: values are updated when domain changes", async () => {
    await mountView({
        type: "form",
        resModel: "partner",
        resId: 1,
        arch: `
                <form>
                    <field name="int_field" />
                    <field name="timmy" widget="many2many_checkboxes" domain="[['id', '>', int_field]]" />
                </form>`,
    });

    expect(".o_field_widget[name='int_field'] input").toHaveValue("10");
    expect(".o_field_widget[name='timmy'] .form-check").toHaveCount(2);
    expect(".o_field_widget[name='timmy']").toHaveText("gold\nsilver");

    await contains(".o_field_widget[name='int_field'] input").edit(13);
    expect(".o_field_widget[name='timmy'] .form-check").toHaveCount(1);
    expect(".o_field_widget[name='timmy']").toHaveText("silver");
});

test("Many2ManyCheckBoxesField with 40+ values", async () => {
    // many2many_checkboxes fetches data via fetchSpecialData (name_search limit of 100),
    // not the default x2many limit of 40. Regression test: (un)selecting a checkbox beyond
    // the first 40 used to crash because BasicModel hadn't processed that field yet.
    expect.assertions(3);

    const records = [];
    for (let id = 1; id <= 90; id++) {
        records.push({
            id,
            name: `type ${id}`,
        });
    }
    PartnerType._records = records;
    Partner._records[0].timmy = records.map((r) => r.id);

    onRpc("web_save", ({ args }) => {
        expect(args[1].timmy).toEqual([[3, records[records.length - 1].id, false]]);
    });
    await mountView({
        type: "form",
        resModel: "partner",
        resId: 1,
        arch: `
            <form>
                <field name="timmy" widget="many2many_checkboxes" />
            </form>`,
    });

    expect(".o_field_widget[name='timmy'] input[type='checkbox']:checked").toHaveCount(
        90,
    );

    await contains(".o_field_widget[name='timmy'] input[type='checkbox']:last").click();
    await runAllTimers();

    await clickSave();
    expect(
        ".o_field_widget[name='timmy'] input[type='checkbox']:last",
    ).not.toBeChecked();
});

test("Many2ManyCheckBoxesField with 100+ values", async () => {
    // Widget caps displayed values at 100 (name_search limit). With >100 records in the
    // relation, (un)selecting a checkbox must not drop the values that aren't displayed.
    expect.assertions(5);

    const records = [];
    for (let id = 1; id < 150; id++) {
        records.push({
            id,
            name: `type ${id}`,
        });
    }
    PartnerType._records = records;
    Partner._records[0].timmy = records.map((r) => r.id);
    onRpc("web_save", ({ args }) => {
        expect(args[1].timmy).toEqual([[3, records[0].id, false]]);
        expect.step("web_save");
    });
    onRpc("name_search", () => {
        expect.step("name_search");
    });

    await mountView({
        type: "form",
        resModel: "partner",
        resId: 1,
        arch: `
            <form>
                <field name="timmy" widget="many2many_checkboxes" />
            </form>`,
    });

    expect(".o_field_widget[name='timmy'] input[type='checkbox']").toHaveCount(100);
    expect(".o_field_widget[name='timmy'] input[type='checkbox']").toBeChecked();

    await contains(".o_field_widget[name='timmy'] input[type='checkbox']").click();
    await runAllTimers();

    await clickSave();
    expect(
        ".o_field_widget[name='timmy'] input[type='checkbox']:first",
    ).not.toBeChecked();
    expect.verifySteps(["name_search", "web_save"]);
});

test("Many2ManyCheckBoxesField in a one2many", async () => {
    expect.assertions(3);

    PartnerType._records.push({ id: 15, name: "bronze" });
    Partner._records[0].timmy = [14, 15];

    onRpc("web_save", ({ args }) => {
        expect(args[1]).toEqual({
            p: [
                [
                    1,
                    1,
                    {
                        timmy: [
                            [4, 12, false],
                            [3, 14, false],
                        ],
                    },
                ],
            ],
        });
    });

    await mountView({
        type: "form",
        resModel: "partner",
        arch: `
            <form>
                <field name="p">
                    <list><field name="id"/></list>
                    <form>
                        <field name="timmy" widget="many2many_checkboxes"/>
                    </form>
                </field>
            </form>`,
        resId: 1,
    });

    await contains(".o_data_cell").click();

    await contains(".modal .form-check-input:eq(0)").click();
    expect(".modal .form-check-input:eq(0)").toBeChecked();
    await contains(".modal .form-check-input:eq(1)").click();
    expect(".modal .form-check-input:eq(1)").not.toBeChecked();

    await contains(".modal .o_form_button_save").click();
    await clickSave();
});

test("Many2ManyCheckBoxesField with default values", async () => {
    expect.assertions(7);

    Partner._fields.timmy = fields.Many2many({
        string: "pokemon",
        relation: "partner.type",
        default: [[4, 3, false]],
    });
    PartnerType._records.push({ id: 3, name: "bronze" });

    onRpc("web_save", ({ args }) => {
        expect(args[1].timmy).toEqual([[4, 12, false]], {
            message: "correct values should have been sent to create",
        });
    });
    await mountView({
        type: "form",
        resModel: "partner",
        arch: `
            <form>
                <field name="timmy" widget="many2many_checkboxes"/>
            </form>`,
    });

    expect(".o_form_view .form-check input:eq(0)").not.toBeChecked();
    expect(".o_form_view .form-check input:eq(1)").not.toBeChecked();
    expect(".o_form_view .form-check input:eq(2)").toBeChecked();

    await contains(".o_form_view .form-check input:checked").click();
    await contains(".o_form_view .form-check input:eq(0)").click();
    await contains(".o_form_view .form-check input:eq(0)").click();
    await contains(".o_form_view .form-check input:eq(0)").click();
    await runAllTimers();

    expect(".o_form_view .form-check input:eq(0)").toBeChecked();
    expect(".o_form_view .form-check input:eq(1)").not.toBeChecked();
    expect(".o_form_view .form-check input:eq(2)").not.toBeChecked();

    await clickSave();
});

test("Many2ManyCheckBoxesField batches successive changes", async () => {
    Partner._fields.timmy = fields.Many2many({
        string: "pokemon",
        relation: "partner.type",
        onChange: () => {},
    });
    Partner._records[0].timmy = [];
    onRpc(({ method }) => {
        expect.step(method);
    });
    await mountView({
        type: "form",
        resModel: "partner",
        resId: 1,
        arch: `
            <form>
                <group>
                    <field name="timmy" widget="many2many_checkboxes" />
                </group>
            </form>`,
    });

    expect("div.o_field_widget div.form-check").toHaveCount(2);
    expect(queryAllTexts(".o_field_widget .form-check-label")).toEqual([
        "gold",
        "silver",
    ]);
    expect("div.o_field_widget div.form-check input:checked").toHaveCount(0);

    await contains("div.o_field_widget div.form-check input:eq(0)").click();
    await contains("div.o_field_widget div.form-check input:eq(1)").click();
    expect("div.o_field_widget div.form-check input:checked").toHaveCount(2);
    expect.verifySteps(["get_views", "web_read", "name_search"]);
    await runAllTimers();
    expect.verifySteps(["onchange"]);
});

test("Many2ManyCheckBoxesField sends batched changes on save", async () => {
    Partner._fields.timmy = fields.Many2many({
        string: "pokemon",
        relation: "partner.type",
        onChange: () => {},
    });
    Partner._records[0].timmy = [];
    onRpc(({ method }) => {
        expect.step(method);
    });
    await mountView({
        type: "form",
        resModel: "partner",
        resId: 1,
        arch: `
            <form>
                <group>
                    <field name="timmy" widget="many2many_checkboxes" />
                </group>
            </form>`,
    });

    expect("div.o_field_widget div.form-check").toHaveCount(2);
    expect(queryAllTexts(".o_field_widget .form-check-label")).toEqual([
        "gold",
        "silver",
    ]);
    expect("div.o_field_widget div.form-check input:checked").toHaveCount(0);

    await contains("div.o_field_widget div.form-check input:eq(0)").click();
    await contains("div.o_field_widget div.form-check input:eq(1)").click();
    expect("div.o_field_widget div.form-check input:checked").toHaveCount(2);
    expect.verifySteps(["get_views", "web_read", "name_search"]);
    await runAllTimers();
    await clickSave();
    expect.verifySteps(["onchange", "web_save"]);
});

test("Many2ManyCheckBoxesField in a notebook tab", async () => {
    Partner._records[0].timmy = [];
    onRpc(({ method }) => {
        expect.step(method);
    });
    await mountView({
        type: "form",
        resModel: "partner",
        resId: 1,
        arch: `
            <form>
                <notebook>
                    <page string="Page 1">
                        <field name="timmy" widget="many2many_checkboxes" />
                    </page>
                    <page string="Page 2">
                        <field name="int_field" />
                    </page>
                </notebook>
            </form>`,
    });

    expect("div.o_field_widget[name=timmy]").toHaveCount(1);
    expect("div.o_field_widget[name=timmy] div.form-check").toHaveCount(2);
    expect(queryAllTexts(".o_field_widget .form-check-label")).toEqual([
        "gold",
        "silver",
    ]);
    expect("div.o_field_widget[name=timmy] div.form-check input:checked").toHaveCount(
        0,
    );

    await contains("div.o_field_widget div.form-check input:eq(0)").click();
    await contains("div.o_field_widget div.form-check input:eq(1)").click();
    expect("div.o_field_widget div.form-check input:checked").toHaveCount(2);
    await contains(".o_notebook .nav-link:eq(1)").click();
    expect("div.o_field_widget[name=timmy]").toHaveCount(0);
    expect("div.o_field_widget[name=int_field]").toHaveCount(1);
    await clickSave();
    expect.verifySteps(["get_views", "web_read", "name_search", "web_save"]);
});
