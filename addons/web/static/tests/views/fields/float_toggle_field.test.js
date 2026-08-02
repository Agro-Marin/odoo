// @ts-check

import { expect, test } from "@odoo/hoot";
import { queryText } from "@odoo/hoot-dom";
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
    float_field = fields.Float({ string: "Float field" });

    _records = [{ id: 1, float_field: 0.44444 }];
}

class User extends models.Model {
    _name = "res.users";
    has_group() {
        return true;
    }
}

defineModels([Partner, User]);

test("basic flow in form view", async () => {
    onRpc("partner", "web_save", ({ args }) => {
        expect.step(args[1].float_field.toString());
    });
    await mountView({
        type: "form",
        resModel: "partner",
        resId: 1,
        arch: `
            <form>
                <field name="float_field" widget="float_toggle" options="{'factor': 0.125, 'range': [0, 1, 0.75, 0.5, 0.25]}" digits="[5,3]"/>
            </form>`,
    });

    expect(".o_field_widget").toHaveText("0.056", {
        message: "The formatted time value should be displayed properly.",
    });
    expect("button.o_field_float_toggle").toHaveText("0.056", {
        message: "The value should be rendered correctly on the button.",
    });

    await contains("button.o_field_float_toggle").click();

    expect("button.o_field_float_toggle").toHaveText("0.000", {
        message: "The value should be rendered correctly on the button.",
    });

    await contains("button.o_field_float_toggle").click();

    expect("button.o_field_float_toggle").toHaveText("1.000", {
        message: "The value should be rendered correctly on the button.",
    });

    await clickSave();

    expect(".o_field_widget").toHaveText("1.000", {
        message: "The new value should be saved and displayed properly.",
    });

    expect.verifySteps(["8"]);
});

test("kanban view (readonly) with option force_button", async () => {
    await mountView({
        type: "kanban",
        resModel: "partner",
        arch: `
            <kanban>
                <templates>
                    <t t-name="card">
                        <field name="float_field" widget="float_toggle" options="{'force_button': true}"/>
                    </t>
                </templates>
            </kanban>`,
    });

    expect("button.o_field_float_toggle").toHaveCount(1, {
        message: "should have rendered toggle button",
    });

    const value = queryText("button.o_field_float_toggle");
    await contains("button.o_field_float_toggle").click();
    expect("button.o_field_float_toggle").not.toHaveText(value, {
        message: "float_field field value should be changed",
    });
});

test("steps from the nearest range value despite float imprecision", async () => {
    Partner._records[0].float_field = 0.1;
    await mountView({
        type: "form",
        resModel: "partner",
        resId: 1,
        arch: `
            <form>
                <field name="float_field" widget="float_toggle" options="{'factor': 3, 'range': [0, 0.3, 0.6]}" digits="[5,2]"/>
            </form>`,
    });

    expect("button.o_field_float_toggle").toHaveText("0.30", {
        message: "0.1 * 3 must render as 0.30",
    });

    await contains("button.o_field_float_toggle").click();

    expect("button.o_field_float_toggle").toHaveText("0.60", {
        message:
            "must advance to the entry after the nearest one (0.3 -> 0.6), not reset to 0.00",
    });
});

test("an unusable range option falls back instead of writing NaN", async () => {
    // `range` is arbitrary arch input; an empty list used to make the index
    // lookup return undefined and store NaN in the record.
    /** @type {Record<string, any> | undefined} */
    let written;
    onRpc("partner", "web_save", ({ args }) => {
        written = args[1];
    });
    await mountView({
        type: "form",
        resModel: "partner",
        resId: 1,
        arch: `<form><field name="float_field" widget="float_toggle" options="{'range': []}"/></form>`,
    });

    await contains(".o_field_float_toggle button").click();
    await clickSave();

    expect(written).toBeInstanceOf(Object);
    expect(Number.isNaN(written?.float_field)).toBe(false, {
        message: "a broken range must never reach the record as NaN",
    });
});
