// @ts-check

/**
 * Setting a many2one to the pair it already holds still runs the onchange, and
 * that is deliberate.
 *
 * It looks like pure waste -- the change set ends up empty and the record ends
 * up clean, so the round trip bought nothing -- and moving the "same pair"
 * filter above the onchange call does remove it. But the model cannot tell the
 * two callers apart:
 *
 *  - the autocomplete handing back the value the user just re-picked, where
 *    nothing has changed;
 *  - ``Many2One``'s internal-link dialog closing, which re-reads the linked
 *    record and calls ``update`` with the SAME pair precisely so the onchange
 *    re-runs: the pointer did not move but the REFERENT did, and the parent's
 *    computed fields may depend on it.
 *
 * Only the widget knows which it is, so the suppression -- if it is ever worth
 * having -- belongs there, not here. ``_update`` runs the onchange either way
 * and only drops the spurious change entry afterwards.
 *
 * The end state is asserted alongside the RPC so a future optimisation cannot
 * quietly trade the onchange for it.
 */

import { expect, test } from "@odoo/hoot";
import { animationFrame } from "@odoo/hoot-mock";
import { Component, xml } from "@odoo/owl";
import {
    defineModels,
    fields,
    findComponent,
    models,
    mountWithCleanup,
    onRpc,
} from "@web/../tests/web_test_helpers";
import { Field } from "@web/fields/field";
import { Record } from "@web/model/record";

class Partner extends models.Model {
    name = fields.Char();
    _records = [
        { id: 7, name: "Seven" },
        { id: 8, name: "Eight" },
    ];
}

class Task extends models.Model {
    name = fields.Char();
    partner_id = fields.Many2one({ relation: "partner" });
    _records = [{ id: 1, name: "T", partner_id: 7 }];
    _onChanges = { partner_id() {} };
}

defineModels([Partner, Task]);

class Parent extends Component {
    static props = ["*"];
    static components = { Record, Field };
    static template = xml`
        <Record resModel="'task'" resId="1"
                activeFields="{ partner_id: { onChange: true } }"
                fieldNames="['partner_id']" t-slot-scope="data">
            <Field name="'partner_id'" record="data.record"/>
        </Record>
    `;
}

/** @returns {Promise<any>} */
async function mountRecord() {
    const parent = await mountWithCleanup(Parent);
    const rec = /** @type {any} */ (findComponent(parent, (c) => c instanceof Record));
    return (
        rec.model?.root ??
        /** @type {any} */ (findComponent(parent, (c) => c.model)).model.root
    );
}

test("re-setting a many2one to its current pair still runs the onchange", async () => {
    const record = await mountRecord();
    onRpc("task", "onchange", () => expect.step("onchange"));

    await record.update({ partner_id: { id: 7, display_name: "Seven" } });
    await animationFrame();

    // The referent may have changed under an unchanged pointer, so the server
    // gets a say. This is what the internal-link dialog depends on.
    expect.verifySteps(["onchange"]);
    // ...but the pointer did not move, so nothing is staged as a change.
    expect(record.dirty).toBe(false);
    expect(Object.keys(record._changes)).toEqual([]);
    expect(record.data.partner_id).toEqual({ id: 7, display_name: "Seven" });
});

test("a genuine many2one change runs the onchange and stages the change", async () => {
    const record = await mountRecord();
    onRpc("task", "onchange", () => expect.step("onchange"));

    await record.update({ partner_id: { id: 8, display_name: "Eight" } });
    await animationFrame();

    expect.verifySteps(["onchange"]);
    expect(record.dirty).toBe(true);
    expect(record.data.partner_id).toEqual({ id: 8, display_name: "Eight" });
});

test("clearing a many2one runs the onchange and stages the change", async () => {
    const record = await mountRecord();
    onRpc("task", "onchange", () => expect.step("onchange"));

    await record.update({ partner_id: false });
    await animationFrame();

    expect.verifySteps(["onchange"]);
    expect(record.dirty).toBe(true);
    expect(record.data.partner_id).toBe(false);
});
