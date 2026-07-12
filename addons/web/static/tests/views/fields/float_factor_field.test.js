// @ts-check

import { expect, test } from "@odoo/hoot";
import {
    clickSave,
    contains,
    defineModels,
    defineParams,
    fields,
    models,
    mountView,
    onRpc,
    patchWithCleanup,
} from "@web/../tests/web_test_helpers";
import { FloatFactorField } from "@web/fields/basic/float_factor/float_factor_field";

class Partner extends models.Model {
    qux = fields.Float();

    _records = [{ id: 1, qux: 9.1 }];
}

defineModels([Partner]);

test("FloatFactorField in form view", async () => {
    expect.assertions(3);

    onRpc("partner", "web_save", ({ args }) => {
        // 2.3 / 0.5 = 4.6
        expect(args[1].qux).toBe(4.6, {
            message: "the correct float value should be saved",
        });
    });
    await mountView({
        type: "form",
        resModel: "partner",
        resId: 1,
        arch: `
            <form>
                <sheet>
                    <field name="qux" widget="float_factor" options="{'factor': 0.5}" digits="[16,2]" />
                </sheet>
            </form>`,
    });
    expect(".o_field_widget[name='qux'] input").toHaveValue("4.55", {
        message: "The value should be rendered correctly in the input.",
    });

    await contains(".o_field_widget[name='qux'] input").edit("2.3");
    await clickSave();

    expect(".o_field_widget input").toHaveValue("2.30", {
        message: "The new value should be saved and displayed properly.",
    });
});

test("FloatFactorField comma as decimal point", async () => {
    expect.assertions(2);

    defineParams({
        lang_parameters: {
            decimal_point: ",",
            thousands_sep: "",
        },
    });
    onRpc("partner", "web_save", ({ args }) => {
        // 2.3 / 0.5 = 4.6
        expect(args[1].qux).toBe(4.6);
        expect.step("save");
    });
    await mountView({
        type: "form",
        resModel: "partner",
        resId: 1,
        arch: `
            <form>
                <sheet>
                    <field name="qux" widget="float_factor" options="{'factor': 0.5}" digits="[16,2]" />
                </sheet>
            </form>`,
    });

    await contains(".o_field_widget[name='qux'] input").edit("2,3");
    await clickSave();

    expect.verifySteps(["save"]);
});

test("FloatFactorField scales += operation input into storage units", async () => {
    expect.assertions(2);

    onRpc("partner", "web_save", ({ args }) => {
        // Displayed value is 4.55 (9.1 * 0.5); "+=1" means displayed 5.55,
        // i.e. stored 11.1. The += operand must be scaled by 1/factor —
        // dividing the Operation object itself would commit NaN.
        expect(args[1].qux).toBe(11.1, {
            message: "the += operand should be scaled back to storage units",
        });
    });
    await mountView({
        type: "form",
        resModel: "partner",
        resId: 1,
        arch: `
            <form>
                <field name="qux" widget="float_factor" options="{'factor': 0.5}" digits="[16,2]" />
            </form>`,
    });

    await contains(".o_field_widget[name='qux'] input").edit("+=1");
    await clickSave();

    expect(".o_field_widget input").toHaveValue("5.55", {
        message: "the displayed value should reflect the operation",
    });
});

test("FloatFactorField passes *= operation input through unscaled", async () => {
    expect.assertions(2);

    onRpc("partner", "web_save", ({ args }) => {
        // "*=2" doubles the displayed value, which doubles the stored value
        // identically: multiplicative operations are scale-invariant.
        expect(args[1].qux).toBe(18.2, {
            message: "the *= operand should not be scaled",
        });
    });
    await mountView({
        type: "form",
        resModel: "partner",
        resId: 1,
        arch: `
            <form>
                <field name="qux" widget="float_factor" options="{'factor': 0.5}" digits="[16,2]" />
            </form>`,
    });

    await contains(".o_field_widget[name='qux'] input").edit("*=2");
    await clickSave();

    expect(".o_field_widget input").toHaveValue("9.10", {
        message: "the displayed value should reflect the doubled amount",
    });
});

test("FloatFactorField.value passes an unset value through as false", () => {
    // An unset float is ``false``; ``false * factor`` would coerce it to 0 and
    // render "0.00" instead of the empty string a plain float renders. The
    // getter must pass ``false`` through so the formatter yields "".
    const makeField = (data, factor) =>
        Object.create(FloatFactorField.prototype, {
            props: {
                value: { record: { data: { qux: data } }, name: "qux", factor },
            },
        });

    expect(makeField(false, 0.5).value).toBe(false, {
        message: "an unset value must stay false, not become 0",
    });
    expect(makeField(9, 0.5).value).toBe(4.5, {
        message: "a set value must still be multiplied by the factor",
    });
});

test("FloatFactorField guards against a zero factor", async () => {
    const warnings = [];
    patchWithCleanup(console, { warn: (...args) => warnings.push(args) });

    await mountView({
        type: "form",
        resModel: "partner",
        resId: 1,
        arch: `
            <form>
                <field name="qux" widget="float_factor" options="{'factor': 0}" digits="[16,2]" />
            </form>`,
    });

    // A zero factor falls back to 1 instead of rendering NaN, and warns.
    expect(".o_field_widget[name='qux'] input").toHaveValue("9.10", {
        message: "a zero factor should fall back to 1",
    });
    expect(warnings.length).toBe(1, {
        message: "a zero factor should emit a warning",
    });
});
