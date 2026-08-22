// @ts-check

import { expect, test } from "@odoo/hoot";
import { animationFrame } from "@odoo/hoot-mock";
import {
    defineModels,
    fields,
    models,
    mountView,
    patchWithCleanup,
} from "@web/../tests/web_test_helpers";
import { RelationalRecord } from "@web/model/relational_model/record";
import { FormController } from "@web/views/form/form_controller";

class Line extends models.Model {
    _name = "line";
    name = fields.Char();
    qty = fields.Integer();
    parent_id = fields.Many2one({ relation: "parent" });
    /** @type {any[]} */
    _records = [];
}

class Parent extends models.Model {
    _name = "parent";
    name = fields.Char();
    ref = fields.Char();
    lines = fields.One2many({ relation: "line", relation_field: "parent_id" });
    /** @type {any[]} */
    _records = [];
}

defineModels([Parent, Line]);

const NB_LINES = 40;

function seed() {
    Line._records = [];
    const ids = [];
    for (let i = 1; i <= NB_LINES; i++) {
        Line._records.push({ id: i, name: `L${i}`, qty: i, parent_id: 1 });
        ids.push(i);
    }
    Parent._records = [{ id: 1, name: "P", ref: "R", lines: ids }];
}

/**
 * @param {string} listContext
 * @returns {Promise<{ record: any, counts: Map<any, number> }>}
 */
async function mountCounting(listContext) {
    seed();
    let controller;
    patchWithCleanup(FormController.prototype, {
        setup() {
            super.setup();
            controller = this;
        },
    });
    /** @type {Map<any, number>} */
    const counts = new Map();
    patchWithCleanup(RelationalRecord.prototype, {
        _setEvalContext() {
            const self = /** @type {any} */ (this);
            counts.set(self.id, (counts.get(self.id) || 0) + 1);
            return super._setEvalContext();
        },
    });
    await mountView({
        type: "form",
        resModel: "parent",
        resId: 1,
        arch: `
            <form>
                <field name="name"/>
                <field name="ref"/>
                <field name="lines" ${listContext}>
                    <list limit="1000">
                        <field name="name"/>
                        <field name="qty"/>
                    </list>
                </field>
            </form>`,
    });
    await animationFrame();
    return { record: /** @type {any} */ (controller).model.root, counts };
}

test("editing a parent field does not rebuild every line's eval context", async () => {
    const { record, counts } = await mountCounting("");
    expect(record.data.lines.records).toHaveLength(NB_LINES);

    counts.clear();
    await record.update({ ref: "R2" });
    await animationFrame();

    const rebuilt = [...counts.values()].reduce((a, b) => a + b, 0);
    expect(counts.get(record.id)).toBe(1, { message: "the parent itself" });
    expect(rebuilt).toBe(1, {
        message: `no line may be walked: ${NB_LINES} lines, ${rebuilt} rebuilds`,
    });
});

test("...but a field the lines' context DEPENDS on does rebuild them", async () => {
    const { record, counts } = await mountCounting(`context="{'default_qty': ref}"`);

    counts.clear();
    await record.update({ ref: "R2" });
    await animationFrame();

    const rebuilt = [...counts.values()].reduce((a, b) => a + b, 0);
    expect(counts.get(record.id)).toBe(1);
    expect(rebuilt).toBeGreaterThan(1, {
        message: "the early return is a correctness-preserving skip, not a blanket one",
    });
});
