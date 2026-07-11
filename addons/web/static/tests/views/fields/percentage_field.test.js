// @ts-check

import { expect, test } from "@odoo/hoot";
import { click, edit, queryOne } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import {
    clickSave,
    defineModels,
    fields,
    models,
    mountView,
    onRpc,
} from "@web/../tests/web_test_helpers";

class Partner extends models.Model {
    float_field = fields.Float({
        string: "Float_field",
        digits: [0, 1],
    });
    _records = [{ float_field: 0.44444 }];
}

defineModels([Partner]);

test("PercentageField in form view", async () => {
    expect.assertions(5);

    onRpc("web_save", ({ args }) => {
        expect(args[1].float_field).toBe(0.24);
    });

    await mountView({
        type: "form",
        resModel: "partner",
        arch: /* xml */ `<form><field name="float_field" widget="percentage"/></form>`,
        resId: 1,
    });

    expect(".o_field_widget[name=float_field] input").toHaveValue("44.4");
    expect(".o_field_widget[name=float_field] span").toHaveText("%", {
        message:
            "The input should be followed by a span containing the percentage symbol.",
    });

    await click("[name='float_field'] input");
    await edit("24");
    expect("[name='float_field'] input").toHaveValue("24");

    await clickSave();

    expect(".o_field_widget input").toHaveValue("24");
});

test("PercentageField in form view without rounding error", async () => {
    await mountView({
        type: "form",
        resModel: "partner",
        arch: /* xml */ `<form><field name="float_field" widget="percentage"/></form>`,
    });

    await click("[name='float_field'] input");
    await edit("28");

    expect("[name='float_field'] input").toHaveValue("28");
});

test("PercentageField input is associated with its form label", async () => {
    await mountView({
        type: "form",
        resModel: "partner",
        arch: /* xml */ `
            <form>
                <group>
                    <field name="float_field" widget="percentage"/>
                </group>
            </form>`,
        resId: 1,
    });

    const input = queryOne("[name='float_field'] input");
    expect(input.id).not.toBe("", {
        message: "the input must carry the field id for the label to bind to",
    });
    expect(`label[for="${input.id}"]`).toHaveCount(1);
});

test("PercentageField in readonly mode renders the symbol", async () => {
    await mountView({
        type: "form",
        resModel: "partner",
        arch: /* xml */ `<form><field name="float_field" widget="percentage" readonly="1"/></form>`,
        resId: 1,
    });

    expect("[name='float_field'] input").toHaveCount(0);
    expect("[name='float_field'] span").toHaveText("44.4%");
});

test("PercentageField parses a %-suffixed input", async () => {
    onRpc("web_save", ({ args }) => {
        expect.step(`float_field: ${args[1].float_field}`);
    });
    await mountView({
        type: "form",
        resModel: "partner",
        arch: /* xml */ `<form><field name="float_field" widget="percentage"/></form>`,
        resId: 1,
    });

    await click("[name='float_field'] input");
    await edit("50%", { confirm: "blur" });
    // The blur commits 0.5, and the input reformats to "50" (dropping the "%")
    // a frame later via the input hook's post-render resync, so wait for it.
    await animationFrame();
    expect("[name='float_field'] input").toHaveValue("50");

    await clickSave();
    expect.verifySteps(["float_field: 0.5"]);
});

test("unset PercentageField renders empty", async () => {
    Partner._records = [{ id: 1, float_field: false }];
    // `read` coerces an unset numeric field to 0; force a genuine `false` so
    // the isFalseEmpty / formatPercentage(false) empty-rendering path is hit.
    onRpc("web_read", ({ parent }) => {
        const result = parent();
        result[0].float_field = false;
        return result;
    });
    await mountView({
        type: "form",
        resModel: "partner",
        arch: /* xml */ `<form><field name="float_field" widget="percentage" readonly="1"/></form>`,
        resId: 1,
    });

    expect("[name='float_field']").toHaveText("", {
        message: "an unset percentage must not render as 0%",
    });
    expect("[name='float_field']").toHaveClass("o_field_empty");
});
