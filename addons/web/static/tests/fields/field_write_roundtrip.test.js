// @ts-check

/**
 * One invariant, checked for every widget that edits through `useInputField`:
 * what the user types must reach `web_save`, under the field the widget claims
 * to edit.
 *
 * `progressbar` broke it. It declared its `current_value` / `max_value` target
 * as a *readonly* field dependency while rendering a writable input for it, and
 * readonly active fields are stripped from `web_save` -- so the edit was
 * accepted, echoed back into the input, and silently dropped, with the form
 * left permanently dirty. Nothing else in the layer had a test for the round
 * trip itself, only for formatting and parsing.
 */

import { expect, test } from "@odoo/hoot";
import { click, edit, press } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import {
    clickSave,
    defineModels,
    fields,
    models,
    mountView,
    onRpc,
} from "@web/../tests/web_test_helpers";

class Currency extends models.Model {
    _name = "res.currency";
    name = fields.Char();
    symbol = fields.Char();
    position = fields.Selection({
        selection: [
            ["before", "Before"],
            ["after", "After"],
        ],
    });
    _records = [{ id: 1, name: "USD", symbol: "$", position: "before" }];
}

class Partner extends models.Model {
    name = fields.Char();
    txt = fields.Text();
    mail = fields.Char();
    tel = fields.Char();
    link = fields.Char();
    num = fields.Integer();
    num2 = fields.Integer();
    amount = fields.Float();
    money = fields.Monetary({ currency_field: "currency_id" });
    currency_id = fields.Many2one({ relation: "res.currency" });
    duration = fields.Float();
    pct = fields.Float();

    _records = [
        {
            id: 1,
            name: "n",
            txt: "t",
            mail: "a@b.c",
            tel: "1",
            link: "http://x",
            num: 1,
            num2: 2,
            amount: 1,
            money: 1,
            currency_id: 1,
            duration: 1,
            pct: 0.1,
        },
    ];
}

class ResUsers extends models.Model {
    _name = "res.users";
    has_group() {
        return true;
    }
}

defineModels([Partner, Currency, ResUsers]);

/** @type {[string, string, string, any][]} */
const CASES = [
    ["name", "", "Zed", "Zed"],
    ["txt", "", "Zed", "Zed"],
    ["mail", "email", "z@z.z", "z@z.z"],
    ["tel", "phone", "999", "999"],
    ["link", "url", "http://z", "http://z"],
    ["num", "", "42", 42],
    ["amount", "", "42.5", 42.5],
    ["money", "monetary", "42.5", 42.5],
    ["duration", "float_time", "02:30", 2.5],
    ["pct", "percentage", "25", 0.25],
];

for (const [fieldName, widget, typed, expected] of CASES) {
    const label = widget ? `${fieldName} (widget=${widget})` : fieldName;
    test(`typed value reaches web_save: ${label}`, async () => {
        onRpc("web_save", ({ args }) => {
            expect.step(args[1]);
        });
        await mountView({
            type: "form",
            resModel: "partner",
            resId: 1,
            arch: `
                <form>
                    <field name="currency_id" invisible="1"/>
                    <field name="${fieldName}"${widget ? ` widget="${widget}"` : ""}/>
                </form>`,
        });

        await click(
            `.o_field_widget[name=${fieldName}] input, .o_field_widget[name=${fieldName}] textarea`,
        );
        await edit(typed);
        await press("Tab");
        await animationFrame();
        await clickSave();

        expect.verifySteps([{ [fieldName]: expected }]);
    });
}

test("typed value reaches web_save: progressbar editing another field", async () => {
    onRpc("web_save", ({ args }) => {
        expect.step(args[1]);
    });
    await mountView({
        type: "form",
        resModel: "partner",
        resId: 1,
        arch: `
            <form>
                <field name="num" widget="progressbar"
                    options="{'editable': true, 'current_value': 'num2'}"/>
            </form>`,
    });

    await click(".o_progressbar_value input");
    await edit("42");
    await press("Tab");
    await animationFrame();
    await clickSave();

    expect.verifySteps([{ num2: 42 }]);
});
