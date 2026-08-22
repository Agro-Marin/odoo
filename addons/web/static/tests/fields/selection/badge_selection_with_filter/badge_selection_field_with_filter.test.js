// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { queryAllTexts } from "@odoo/hoot-dom";
import {
    contains,
    defineModels,
    fields,
    models,
    mountView,
} from "@web/../tests/web_test_helpers";

class Partner extends models.Model {
    _name = "res.partner";
    _inherit = [];

    state = fields.Selection({
        selection: [
            ["draft", "Draft"],
            ["sent", "Sent"],
            ["done", "Done"],
            ["cancel", "Cancelled"],
        ],
        default: "draft",
    });
    allowed_states = fields.Json();

    _records = [
        { id: 1, state: "draft", allowed_states: ["draft", "sent"] },
        { id: 2, state: "done", allowed_states: ["cancel"] },
    ];
}

defineModels([Partner]);

const ARCH = `
    <form>
        <field name="allowed_states" invisible="1"/>
        <field name="state" widget="selection_badge_with_filter"
               options="{'allowed_selection_field': 'allowed_states'}"/>
    </form>`;

const BADGES = ".o_field_widget[name='state'] .o_selection_badge";

describe("filtering", () => {
    test("only the allowed values are offered", async () => {
        await mountView({
            type: "form",
            resModel: "res.partner",
            resId: 1,
            arch: ARCH,
        });
        expect(queryAllTexts(BADGES)).toEqual(["Draft", "Sent"]);
    });

    test("the current value is always offered, allowed or not", async () => {
        await mountView({
            type: "form",
            resModel: "res.partner",
            resId: 2,
            arch: ARCH,
        });
        expect(queryAllTexts(BADGES)).toEqual(["Done", "Cancelled"]);
    });

    test("an empty allowed list leaves only the current value", async () => {
        Partner._records[0].allowed_states = [];
        await mountView({
            type: "form",
            resModel: "res.partner",
            resId: 1,
            arch: ARCH,
        });
        expect(queryAllTexts(BADGES)).toEqual(["Draft"]);
    });

    test("picking an allowed value writes it", async () => {
        await mountView({
            type: "form",
            resModel: "res.partner",
            resId: 1,
            arch: ARCH,
        });
        await contains(`${BADGES}:not(.active)`).click();
        expect(`${BADGES}.active`).toHaveText("Sent");
    });
});

describe("without the option", () => {
    test("falls back to offering every value", async () => {
        await mountView({
            type: "form",
            resModel: "res.partner",
            resId: 1,
            arch: `<form><field name="state" widget="selection_badge_with_filter"/></form>`,
        });
        expect(queryAllTexts(BADGES)).toEqual(["Draft", "Sent", "Done", "Cancelled"]);
    });
});
