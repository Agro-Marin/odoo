// @ts-check

import { expect, test } from "@odoo/hoot";
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
    qux = fields.Float();

    _records = [{ id: 5, qux: 9.1 }];
}

defineModels([Partner]);

test("FloatTimeField in form view", async () => {
    expect.assertions(4);
    onRpc("partner", "web_save", ({ args }) => {
        expect(args[1].qux).toBe(-11.8, {
            message: "the correct float value should be saved",
        });
    });

    await mountView({
        type: "form",
        resModel: "partner",
        arch: `
            <form>
                <sheet>
                    <field name="qux" widget="float_time"/>
                </sheet>
            </form>`,
        resId: 5,
    });

    expect(".o_field_float_time[name=qux] input").toHaveValue("09:06", {
        message: "The value should be rendered correctly in the input.",
    });

    await contains(".o_field_float_time[name=qux] input").edit("-11:48");
    expect(".o_field_float_time[name=qux] input").toHaveValue("-11:48", {
        message: "The new value should be displayed properly in the input.",
    });

    await clickSave();
    expect(".o_field_widget input").toHaveValue("-11:48", {
        message: "The new value should be saved and displayed properly.",
    });
});

test("FloatTimeField value formatted on blur", async () => {
    expect.assertions(4);
    onRpc("partner", "web_save", ({ args }) => {
        expect(args[1].qux).toBe(9.5, {
            message: "the correct float value should be saved",
        });
    });
    await mountView({
        type: "form",
        resModel: "partner",
        arch: `
            <form>
                <field name="qux" widget="float_time"/>
            </form>`,
        resId: 5,
    });

    expect(".o_field_widget input").toHaveValue("09:06", {
        message: "The formatted time value should be displayed properly.",
    });

    await contains(".o_field_float_time[name=qux] input").edit("9.5");
    expect(".o_field_float_time[name=qux] input").toHaveValue("09:30", {
        message: "The new value should be displayed properly in the input.",
    });

    await clickSave();
    expect(".o_field_widget input").toHaveValue("09:30", {
        message: "The new value should be saved and displayed properly.",
    });
});

test("FloatTimeField with invalid value", async () => {
    await mountView({
        type: "form",
        resModel: "partner",
        arch: `
            <form>
                <field name="qux" widget="float_time"/>
            </form>`,
    });

    await contains(".o_field_float_time[name=qux] input").edit("blabla");
    await clickSave();
    expect(".o_notification_content").toHaveText("Missing required fields");
    expect(".o_notification_bar").toHaveClass("bg-danger");
    expect(".o_field_float_time[name=qux]").toHaveClass("o_field_invalid");

    await contains(".o_field_float_time[name=qux] input").edit("6.5");
    expect(".o_field_float_time[name=qux] input").not.toHaveClass("o_field_invalid", {
        message: "date field should not be displayed as invalid now",
    });
});

test("float_time field does not have an inputmode attribute", async () => {
    await mountView({
        type: "form",
        resModel: "partner",
        arch: `
            <form>
                <field name="qux" widget="float_time"/>
            </form>`,
    });

    expect(".o_field_widget[name='qux'] input").not.toHaveAttribute("inputmode");
});

test("display_seconds is honoured under the conventional spelling", async () => {
    // `displaySeconds` is the historical camelCase name and stays live for the
    // arches that already use it; `display_seconds` is the spelling every other
    // option in this module uses and used to do nothing at all.
    for (const option of ["display_seconds", "displaySeconds"]) {
        await mountView({
            type: "form",
            resModel: "partner",
            resId: 5,
            arch: `<form><field name="qux" widget="float_time" options="{'${option}': True}"/></form>`,
        });
        expect(`[name='qux'] input`).toHaveValue("09:06:00", {
            message: `seconds shown for options={'${option}': True}`,
        });
    }
});

test("no seconds without the option", async () => {
    await mountView({
        type: "form",
        resModel: "partner",
        resId: 5,
        arch: `<form><field name="qux" widget="float_time"/></form>`,
    });
    expect(`[name='qux'] input`).toHaveValue("09:06");
});
