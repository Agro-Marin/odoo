// @ts-check

import { expect, test } from "@odoo/hoot";
import { click } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import {
    defineModels,
    fields,
    models,
    mountView,
    onRpc,
} from "@web/../tests/web_test_helpers";

class Partner extends models.Model {
    is_raining_outside = fields.Boolean();
    mood = fields.Selection({
        selection: [
            ["happy", "Happy"],
            ["sad", "Sad"],
        ],
    });
    color = fields.Selection({
        selection: [
            ["white", "White"],
            ["grey", "Grey"],
            ["black", "Black"],
        ],
    });
    allowed_colors = fields.Json();
    allowed_moods = fields.Json();

    _onChanges = {
        is_raining_outside(record) {
            record.allowed_moods =
                ["happy"] + (record.is_raining_outside ? ["sad"] : []);
        },
        color(record) {
            record.allowed_moods =
                (record.color !== "black" ? ["happy"] : []) +
                (record.color !== "white" ? ["sad"] : []);
        },
        mood(record) {
            record.allowed_colors =
                (record.mood === "happy" ? ["white"] : []) +
                ["grey"] +
                (record.mood === "sad" ? ["black"] : []);
        },
    };

    _records = [
        {
            id: 1,
            allowed_colors: "['white', 'grey']",
            allowed_moods: "['happy']",
            display_name: "first record",
            is_raining_outside: false,
            mood: "happy",
            color: "white",
        },
    ];
}

defineModels([Partner]);

test("badge selection field with filter, empty list", async () => {
    // An empty allowed list hides every value the record does not hold. The
    // stored one stays: filtering it away too left the widget with no badge
    // selected while the record held "white", which reads as an empty field and
    // gives the user no way to see -- or restore -- the value that is there.
    Partner._records[0].allowed_colors = [];
    await mountView({
        type: "form",
        resModel: "partner",
        resId: 1,
        arch: `
            <form>
                <field name="allowed_colors" invisible="1"/>
                <field name="color" widget="selection_badge_with_filter"
                    options="{'allowed_selection_field': 'allowed_colors'}"/>
            </form>
        `,
    });

    expect(".o_selection_badge").toHaveCount(1);
    expect(".o_selection_badge[value='\"white\"']").toHaveClass("active");
    expect(".o_selection_badge[value='\"grey\"']").toHaveCount(0);
    expect(".o_selection_badge[value='\"black\"']").toHaveCount(0);
});

test("badge selection field with filter, stored value already allowed", async () => {
    Partner._records[0].allowed_colors = ["white", "grey"];
    await mountView({
        type: "form",
        resModel: "partner",
        resId: 1,
        arch: `
            <form>
                <field name="allowed_colors" invisible="1"/>
                <field name="color" widget="selection_badge_with_filter"
                    options="{'allowed_selection_field': 'allowed_colors'}"/>
            </form>
        `,
    });

    // Kept once, not twice.
    expect(".o_selection_badge").toHaveCount(2);
    expect(".o_selection_badge[value='\"white\"']").toHaveCount(1);
});

test("badge selection field with filter, single choice", async () => {
    Partner._records[0].allowed_colors = ["grey"];
    await mountView({
        type: "form",
        resModel: "partner",
        resId: 1,
        arch: `
            <form>
                <field name="allowed_colors" invisible="1"/>
                <field name="color" widget="selection_badge_with_filter"
                    options="{'allowed_selection_field': 'allowed_colors'}"/>
            </form>
        `,
    });

    // "white" is what the record holds, so it stays offered and selected next
    // to the single allowed value.
    expect(".o_selection_badge").toHaveCount(2);
    expect(".o_selection_badge[value='\"white\"']").toHaveClass("active");
    expect(".o_selection_badge[value='\"grey\"']").toBeVisible();
    expect(".o_selection_badge[value='\"black\"']").toHaveCount(0);
});

test("badge selection field with filter, all choices", async () => {
    Partner._records[0].allowed_colors = ["white", "grey", "black"];
    await mountView({
        type: "form",
        resModel: "partner",
        resId: 1,
        arch: `
            <form>
                <field name="allowed_colors" invisible="1"/>
                <field name="color" widget="selection_badge_with_filter"
                    options="{'allowed_selection_field': 'allowed_colors'}"/>
            </form>
        `,
    });

    expect(".o_selection_badge").toHaveCount(3);
    expect(".o_selection_badge[value='\"white\"']").toBeVisible();
    expect(".o_selection_badge[value='\"grey\"']").toBeVisible();
    expect(".o_selection_badge[value='\"black\"']").toBeVisible();
});

test("badge selection field with filter, synchronize with other field", async () => {
    await mountView({
        type: "form",
        resModel: "partner",
        resId: 1,
        arch: `
            <form>
                <group>
                    <field name="is_raining_outside"/>
                    <field name="allowed_moods" invisible="1"/>
                    <field name="mood" widget="selection_badge_with_filter"
                        options="{'allowed_selection_field': 'allowed_moods'}"/>
                </group>
            </form>
        `,
    });
    expect("[name='is_raining_outside'] input").not.toBeChecked();
    expect("div[name='mood'] .o_selection_badge").toHaveCount(1);
    expect(".o_selection_badge[value='\"happy\"']").toBeVisible();
    expect(".o_selection_badge[value='\"sad\"']").toHaveCount(0);

    await click("[name='is_raining_outside'] input");
    await animationFrame();

    expect("[name='is_raining_outside'] input").toBeChecked();
    expect("div[name='mood'] .o_selection_badge").toHaveCount(2);
    expect(".o_selection_badge[value='\"happy\"']").toBeVisible();
    expect(".o_selection_badge[value='\"sad\"']").toBeVisible();

    await click("[name='is_raining_outside'] input");
    await animationFrame();

    expect("[name='is_raining_outside'] input").not.toBeChecked();
    expect("div[name='mood'] .o_selection_badge").toHaveCount(1);
    expect(".o_selection_badge[value='\"happy\"']").toBeVisible();
    expect(".o_selection_badge[value='\"sad\"']").toHaveCount(0);
});

test("badge selection field with filter, cross badge synchronization", async () => {
    await mountView({
        type: "form",
        resModel: "partner",
        resId: 1,
        arch: `
            <form>
                <group>
                    <field name="allowed_moods"/>
                    <field name="allowed_colors"/>
                    <field name="mood" widget="selection_badge_with_filter" 
                        options="{'allowed_selection_field': 'allowed_moods'}"/>
                    <field name="color" widget="selection_badge_with_filter"
                        options="{'allowed_selection_field': 'allowed_colors'}"/>
                </group>
            </form>
        `,
    });

    expect("div[name='mood'] .o_selection_badge").toHaveCount(1);
    expect("div[name='color'] .o_selection_badge").toHaveCount(2);
    expect(".o_selection_badge[value='\"happy\"']").toBeVisible();
    expect(".o_selection_badge[value='\"sad\"']").toHaveCount(0);
    expect(".o_selection_badge[value='\"white\"']").toBeVisible();
    expect(".o_selection_badge[value='\"grey\"']").toBeVisible();
    expect(".o_selection_badge[value='\"black\"']").toHaveCount(0);

    await click(".o_selection_badge[value='\"grey\"']");
    await animationFrame();

    expect("div[name='mood'] .o_selection_badge").toHaveCount(2);
    expect("div[name='color'] .o_selection_badge").toHaveCount(2);
    expect(".o_selection_badge[value='\"happy\"']").toBeVisible();
    expect(".o_selection_badge[value='\"sad\"']").toBeVisible();
    expect(".o_selection_badge[value='\"white\"']").toBeVisible();
    expect(".o_selection_badge[value='\"grey\"']").toBeVisible();
    expect(".o_selection_badge[value='\"black\"']").toHaveCount(0);

    await click(".o_selection_badge[value='\"sad\"']");
    await animationFrame();

    expect("div[name='mood'] .o_selection_badge").toHaveCount(2);
    expect("div[name='color'] .o_selection_badge").toHaveCount(2);
    expect(".o_selection_badge[value='\"happy\"']").toBeVisible();
    expect(".o_selection_badge[value='\"sad\"']").toBeVisible();
    expect(".o_selection_badge[value='\"white\"']").toHaveCount(0);
    expect(".o_selection_badge[value='\"grey\"']").toBeVisible();
    expect(".o_selection_badge[value='\"black\"']").toBeVisible();

    await click(".o_selection_badge[value='\"black\"']");
    await animationFrame();

    expect("div[name='mood'] .o_selection_badge").toHaveCount(1);
    expect("div[name='color'] .o_selection_badge").toHaveCount(2);
    expect(".o_selection_badge[value='\"happy\"']").toHaveCount(0);
    expect(".o_selection_badge[value='\"sad\"']").toBeVisible();
    expect(".o_selection_badge[value='\"white\"']").toHaveCount(0);
    expect(".o_selection_badge[value='\"grey\"']").toBeVisible();
    expect(".o_selection_badge[value='\"black\"']").toBeVisible();
});

test("the allowed-values field is loaded without the view naming it", async () => {
    // Every consumer used to need an `<field name="..." invisible="1"/>` of its
    // own; forgetting it left `allowed_selection_field` absent from the record,
    // which filtered every option away instead of failing visibly.
    Partner._records[0].allowed_colors = ["grey", "black"];
    // An allowed value, so "white" is filtered on its own merits and the
    // assertions below still show the filter doing something.
    Partner._records[0].color = "grey";
    onRpc("web_read", ({ kwargs }) => {
        expect(Object.keys(kwargs.specification)).toInclude("allowed_colors");
    });
    await mountView({
        type: "form",
        resModel: "partner",
        resId: 1,
        arch: `
            <form>
                <field name="color" widget="selection_badge_with_filter"
                    options="{'allowed_selection_field': 'allowed_colors'}"/>
            </form>
        `,
    });

    expect(".o_selection_badge").toHaveCount(2);
    expect(".o_selection_badge[value='\"white\"']").toHaveCount(0);
});
