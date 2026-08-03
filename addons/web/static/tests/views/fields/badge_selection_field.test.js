// @ts-check

import { expect, test } from "@odoo/hoot";
import { press, queryOne } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import {
    clickSave,
    contains,
    defineModels,
    fields,
    MockServer,
    models,
    mountView,
    onRpc,
} from "@web/../tests/web_test_helpers";

class Partner extends models.Model {
    _name = "res.partner";

    product_id = fields.Many2one({ relation: "product" });
    color = fields.Selection({
        selection: [
            ["red", "Red"],
            ["black", "Black"],
        ],
        default: "red",
    });
    product_color_id = fields.Integer({
        relation: "product",
        related: "product_id.color",
        default: 20,
    });

    _records = [{ id: 1 }, { id: 2, product_id: 37, product_color_id: 6 }];
}

class Product extends models.Model {
    _rec_name = "display_name";

    name = fields.Char("name");
    color = fields.Integer("color");

    _records = [
        { id: 37, display_name: "xphone", name: "xphone", color: 6 },
        { id: 41, display_name: "xpad", name: "xpad", color: 7 },
    ];
}

defineModels([Partner, Product]);

onRpc("has_group", () => true);

test("BadgeSelectionField widget on a many2one in a new record", async () => {
    onRpc("web_save", ({ args }) => {
        expect.step(`saved product_id: ${args[1]["product_id"]}`);
    });

    await mountView({
        resModel: "res.partner",
        type: "form",
        arch: `<form><field name="product_id" widget="selection_badge"/></form>`,
    });

    expect(`div.o_field_selection_badge`).toHaveCount(1, {
        message: "should have rendered outer div",
    });
    expect(`span.o_selection_badge`).toHaveCount(2, {
        message: "should have 2 possible choices",
    });
    expect(`span.o_selection_badge:contains(xphone)`).toHaveCount(1, {
        message: "one of them should be xphone",
    });
    expect(`span.active`).toHaveCount(0, {
        message: "none of the input should be checked",
    });

    await contains(`span.o_selection_badge`).click();
    expect(`span.active`).toHaveCount(1, {
        message: "one of the input should be checked",
    });

    await clickSave();
    expect.verifySteps(["saved product_id: 37"]);
});

test("BadgeSelectionField widget on a selection in a new record", async () => {
    onRpc("web_save", ({ args }) => {
        expect.step(`saved color: ${args[1]["color"]}`);
    });
    await mountView({
        resModel: "res.partner",
        type: "form",
        arch: `<form><field name="color" widget="selection_badge"/></form>`,
    });

    expect(`div.o_field_selection_badge`).toHaveCount(1, {
        message: "should have rendered outer div",
    });
    expect("span.o_selection_badge").toHaveCount(2, {
        message: "should have 2 possible choices",
    });
    expect(`span.o_selection_badge:contains(Red)`).toHaveCount(1, {
        message: "one of them should be Red",
    });

    await contains(`span.o_selection_badge:last`).click();
    await clickSave();
    expect.verifySteps(["saved color: black"]);
});

test("BadgeSelectionField widget exposes radiogroup semantics and keyboard activation", async () => {
    onRpc("web_save", ({ args }) => {
        expect.step(`saved color: ${args[1]["color"]}`);
    });
    await mountView({
        resModel: "res.partner",
        type: "form",
        arch: `<form><field name="color" widget="selection_badge"/></form>`,
    });

    expect("div.o_field_selection_badge [role='radiogroup']").toHaveCount(1);
    expect("span.o_selection_badge[role='radio']").toHaveCount(2);
    expect("span.o_selection_badge[tabindex='0']").toHaveCount(2);
    expect("span.o_selection_badge[aria-checked='true']").toHaveCount(1);
    expect("span.o_selection_badge[aria-checked='true']").toHaveText("Red");

    queryOne("span.o_selection_badge:last").focus();
    await press("Enter");
    await animationFrame();
    expect("span.o_selection_badge[aria-checked='true']").toHaveText("Black", {
        message: "Enter must activate the focused badge",
    });
    await clickSave();
    expect.verifySteps(["saved color: black"]);
});

test("BadgeSelectionField widget on a selection in a readonly mode", async () => {
    await mountView({
        resModel: "res.partner",
        type: "form",
        arch: `<form><field name="color" widget="selection_badge" readonly="1"/></form>`,
    });
    expect(`div.o_readonly_modifier span`).toHaveCount(1, {
        message: "should have 1 possible value in readonly mode",
    });
    expect(`div.o_readonly_modifier span`).toHaveText("Red");
});

test("BadgeSelectionField widget on a selection unchecking selected value", async () => {
    onRpc("res.partner", "web_save", ({ args }) => {
        expect.step("web_save");
        expect(args[1]).toEqual({ color: false });
    });
    await mountView({
        type: "form",
        resModel: "res.partner",
        arch: '<form><field name="color" widget="selection_badge"/></form>',
    });

    expect("div.o_field_selection_badge").toHaveCount(1, {
        message: "should have rendered outer div",
    });
    expect("span.o_selection_badge").toHaveCount(2, {
        message: "should have 2 possible choices",
    });
    expect("span.o_selection_badge.active").toHaveCount(1, {
        message: "one is active",
    });
    expect("span.o_selection_badge.active").toHaveText("Red", {
        message: "the active one should be Red",
    });

    await contains("span.o_selection_badge.active").click();
    expect.verifySteps([]);
    await contains(".o_form_button_save").click();
    expect.verifySteps(["web_save"]);

    expect(MockServer.env["res.partner"].at(-1).color).toBe(false, {
        message:
            "the new value should be false as we have selected same value as default",
    });
});

test("BadgeSelectionField widget on a selection unchecking selected value (required field)", async () => {
    Partner._fields.color.required = true;
    onRpc("res.partner", "web_save", ({ args }) => {
        expect.step("web_save");
        expect(args[1]).toEqual({ color: "red" });
    });
    await mountView({
        type: "form",
        resModel: "res.partner",
        arch: '<form><field name="color" widget="selection_badge"/></form>',
    });

    expect("div.o_field_selection_badge").toHaveCount(1, {
        message: "should have rendered outer div",
    });
    expect("span.o_selection_badge").toHaveCount(2, {
        message: "should have 2 possible choices",
    });
    expect("span.o_selection_badge.active").toHaveCount(1, {
        message: "one is active",
    });
    expect("span.o_selection_badge.active").toHaveText("Red", {
        message: "the active one should be Red",
    });

    await contains("span.o_selection_badge.active").click();
    expect.verifySteps([]);
    await contains(".o_form_button_save").click();
    expect.verifySteps(["web_save"]);

    expect(MockServer.env["res.partner"].at(-1).color).toBe("red", {
        message: "the new value should be red",
    });
});

test("BadgeSelectionField respects arch/dynamic required when unchecking", async () => {
    await mountView({
        type: "form",
        resModel: "res.partner",
        arch: '<form><field name="color" widget="selection_badge" required="1"/></form>',
    });

    expect("span.o_selection_badge.active").toHaveText("Red");

    await contains("span.o_selection_badge.active").click();
    expect("span.o_selection_badge.active").toHaveCount(1);
    expect("span.o_selection_badge.active").toHaveText("Red", {
        message: "arch-required badge must not deselect on re-click",
    });
});

test("BadgeSelectionField widget in list with the color_field option", async () => {
    await mountView({
        resModel: "res.partner",
        type: "list",
        arch: `
            <list editable="top">
                <field name="product_color_id" invisible="1"/>
                <field name="product_id" widget="selection_badge" options="{'color_field': 'product_color_id'}"/>
            </list>
        `,
    });

    expect(`.o_field_selection_badge[name="product_id"] .o_badge_color_6`).toHaveCount(
        1,
    );
    expect(`.o_field_selection_badge[name="product_id"] .o_badge_color_7`).toHaveCount(
        0,
    );
    expect(`div.o_field_selection_badge span:contains(xphone)`).toHaveCount(1);
    expect(`div.o_field_selection_badge span:contains(xpad)`).toHaveCount(0);

    await contains(
        `.o_field_selection_badge[name="product_id"] .o_badge_color_6`,
    ).click();

    expect("span.btn-secondary.badge").toHaveCount(2);
    expect(`span.btn-secondary.active:contains(xphone)`).toHaveCount(1);
    expect(`span.btn-secondary.active:contains(xpad)`).toHaveCount(0);

    await contains(`span.btn-secondary:contains(xpad)`).click();

    expect(`span.btn-secondary.active:contains(xphone)`).toHaveCount(0);
    expect(`span.btn-secondary.active:contains(xpad)`).toHaveCount(1);

    await contains(".o_list_button_save").click();

    expect(`.o_field_selection_badge[name="product_id"] .o_badge_color_6`).toHaveCount(
        0,
    );
    expect(`.o_field_selection_badge[name="product_id"] .o_badge_color_7`).toHaveCount(
        1,
    );
    expect(`div.o_field_selection_badge span:contains(xphone)`).toHaveCount(0);
    expect(`div.o_field_selection_badge span:contains(xpad)`).toHaveCount(1);
});

test("BadgeSelectionField widget in list without the color_field option", async () => {
    await mountView({
        resModel: "res.partner",
        type: "list",
        arch: `
            <list editable="top">
                <field name="id"/>
                <field name="product_id" widget="selection_badge"/>
            </list>
        `,
    });

    expect(`div.o_field_selection_badge span.btn-secondary`).toHaveCount(1);
    expect(
        `div.o_field_selection_badge span.btn-secondary:contains(xphone)`,
    ).toHaveCount(1);
    expect(`div.o_field_selection_badge span.btn-secondary:contains(xpad)`).toHaveCount(
        0,
    );

    await contains(`div.o_field_selection_badge span:contains(xphone)`).click();

    expect("span.btn-secondary.badge").toHaveCount(2);
    expect(`span.btn-secondary.active:contains(xphone)`).toHaveCount(1);
    expect(`span.btn-secondary.active:contains(xpad)`).toHaveCount(0);

    await contains(`span.btn-secondary:contains(xpad)`).click();

    expect(`span.btn-secondary.active:contains(xphone)`).toHaveCount(0);
    expect(`span.btn-secondary.active:contains(xpad)`).toHaveCount(1);

    await contains(".o_list_button_save").click();

    expect(`div.o_field_selection_badge span.btn-secondary`).toHaveCount(1);
    expect(
        `div.o_field_selection_badge span.btn-secondary:contains(xphone)`,
    ).toHaveCount(0);
    expect(`div.o_field_selection_badge span.btn-secondary:contains(xpad)`).toHaveCount(
        1,
    );
});

test("the list badge's color_field is loaded without the view naming it", async () => {
    // `badgeColorClass` reads the colour out of `record.data`. Without a
    // declared dependency the field was absent from the read, so the badge fell
    // back to the plain style and the option silently did nothing unless the
    // arch also carried a `<field name="..." column_invisible="1"/>` for it.
    onRpc("web_search_read", ({ kwargs }) => {
        expect(Object.keys(kwargs.specification)).toInclude("product_color_id");
    });
    await mountView({
        type: "list",
        resModel: "res.partner",
        arch: `
            <list>
                <field name="color" widget="selection_badge"
                    options="{'color_field': 'product_color_id'}"/>
            </list>`,
    });
    expect(".o_data_row:eq(1) .badge").toHaveClass("o_badge_color_6");
});
