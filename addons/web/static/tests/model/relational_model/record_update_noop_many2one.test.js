// @ts-check

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

    expect.verifySteps(["onchange"]);
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
