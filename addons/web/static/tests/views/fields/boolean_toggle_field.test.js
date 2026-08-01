// @ts-check

import { expect, test } from "@odoo/hoot";
import { check, click } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import {
    defineModels,
    defineWebModels,
    fields,
    models,
    mountView,
    onRpc,
} from "@web/../tests/web_test_helpers";

class Partner extends models.Model {
    bar = fields.Boolean({ default: true });

    _records = [{ id: 1, bar: false }];
}

defineWebModels();
defineModels([Partner]);

test("use BooleanToggleField in form view", async () => {
    await mountView({
        resModel: "partner",
        resId: 1,
        type: "form",
        arch: `<form><field name="bar" widget="boolean_toggle"/></form>`,
    });
    expect(`.form-check.o_boolean_toggle`).toHaveCount(1);
    expect(`.o_boolean_toggle input`).toBeEnabled();
    expect(`.o_boolean_toggle input`).not.toBeChecked();

    await check(`.o_field_widget[name='bar'] input`);
    await animationFrame();
    expect(`.o_boolean_toggle input`).toBeEnabled();
    expect(`.o_boolean_toggle input`).toBeChecked();
});

test("BooleanToggleField is disabled with a readonly attribute", async () => {
    await mountView({
        resModel: "partner",
        resId: 1,
        type: "form",
        arch: `<form><field name="bar" widget="boolean_toggle" readonly="1"/></form>`,
    });
    expect(`.form-check.o_boolean_toggle`).toHaveCount(1);
    expect(`.o_boolean_toggle input`).not.toBeEnabled();
});

test("BooleanToggleField is disabled if readonly in editable list", async () => {
    Partner._fields.bar.readonly = true;

    onRpc("has_group", () => true);
    await mountView({
        resModel: "partner",
        type: "list",
        arch: `
            <list editable="bottom">
                <field name="bar" widget="boolean_toggle"/>
            </list>
        `,
    });
    expect(`.o_boolean_toggle input`).not.toBeEnabled();
    expect(`.o_boolean_toggle input`).not.toBeChecked();

    await click(`.o_boolean_toggle`);
    await animationFrame();
    expect(`.o_boolean_toggle input`).not.toBeEnabled();
    expect(`.o_boolean_toggle input`).not.toBeChecked();
});

test("BooleanToggleField - auto save record when field toggled", async () => {
    onRpc("web_save", () => expect.step("web_save"));
    await mountView({
        resModel: "partner",
        resId: 1,
        type: "form",
        arch: `<form><field name="bar" widget="boolean_toggle"/></form>`,
    });
    await click(`.o_field_widget[name='bar'] input`);
    await animationFrame();
    expect.verifySteps(["web_save"]);
});

test("BooleanToggleField - autosave option set to false", async () => {
    onRpc("web_save", () => expect.step("web_save"));
    await mountView({
        resModel: "partner",
        resId: 1,
        type: "form",
        arch: `<form><field name="bar" widget="boolean_toggle" options="{'autosave': false}"/></form>`,
    });
    await click(`.o_field_widget[name='bar'] input`);
    await animationFrame();
    expect.verifySteps([]);
});

test("boolean_toggle stays clickable on a row that is not being edited", async () => {
    // `boolean_toggle` and the plain `boolean` share one template, whose
    // checkbox is bound to `props.readonly`. The toggle stays clickable because
    // its registry entry declares `interactiveOutsideEdition`; the plain
    // checkbox does not declare it, and is disabled (next test).
    await mountView({
        resModel: "partner",
        type: "list",
        arch: `<list><field name="bar" widget="boolean_toggle"/></list>`,
    });
    expect(`.o_data_row td[name=bar] input`).toBeEnabled();
});

test("a plain boolean on the same row is not clickable", async () => {
    await mountView({
        resModel: "partner",
        type: "list",
        arch: `<list><field name="bar"/></list>`,
    });
    expect(`.o_data_row td[name=bar] input`).not.toBeEnabled();
});
