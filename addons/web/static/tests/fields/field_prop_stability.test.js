// @ts-check

import { expect, test } from "@odoo/hoot";
import { animationFrame } from "@odoo/hoot-mock";
import {
    contains,
    defineModels,
    fields,
    models,
    mountView,
} from "@web/../tests/web_test_helpers";

class Tag extends models.Model {
    _name = "tag";
    name = fields.Char();
    _records = [{ id: 1, name: "t1" }];
}

class Partner extends models.Model {
    name = fields.Char();
    other = fields.Char();
    tag_ids = fields.Many2many({ relation: "tag" });
    _records = [{ id: 1, name: "p", other: "o", tag_ids: [1] }];
}

class ResUsers extends models.Model {
    _name = "res.users";
    has_group() {
        return true;
    }
}

defineModels([Partner, Tag, ResUsers]);

/**
 * @param {() => Promise<void>} workload
 * @returns {Promise<Record<string, number>>}
 */
async function renderCounts(workload) {
    const g = /** @type {any} */ (globalThis);
    g.__renderTrace = true;
    g.__renderReset();
    try {
        await workload();
    } finally {
        g.__renderTrace = false;
    }
    return g.__renderStats();
}

test("a widget re-renders once per unrelated committed edit", async () => {
    await mountView({
        type: "form",
        resModel: "partner",
        resId: 1,
        arch: `
            <form>
                <field name="name"/>
                <field name="other"/>
                <field name="tag_ids" widget="many2many_tags"/>
            </form>`,
    });
    await animationFrame();

    const stats = await renderCounts(async () => {
        for (const value of ["x", "xy", "xyz", "xyza", "xyzab"]) {
            await contains("[name='name'] input").edit(value);
            await animationFrame();
        }
    });

    expect(stats["fields.CharField"]).toBe(5);
    expect(stats["fields.Many2ManyTagsField"]).toBe(5);
});
