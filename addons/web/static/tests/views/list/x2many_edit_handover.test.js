// @ts-check

import { expect, test } from "@odoo/hoot";
import { animationFrame } from "@odoo/hoot-mock";
import {
    contains,
    defineModels,
    fields,
    models,
    mountView,
    webModels,
} from "@web/../tests/web_test_helpers";

class Line extends models.Model {
    _name = "line";
    name = fields.Char();
    qty = fields.Integer();

    _records = Array.from({ length: 30 }, (_, i) => ({
        id: i + 1,
        name: `line ${i + 1}`,
        qty: i,
    }));
}

class Order extends models.Model {
    _name = "order";
    line_ids = fields.One2many({ relation: "line" });

    _records = [{ id: 1, line_ids: Array.from({ length: 30 }, (_, i) => i + 1) }];
}

defineModels([...Object.values(webModels), Order, Line]);

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

const ARCH = `
    <form>
        <field name="line_ids">
            <list editable="bottom">
                <field name="name"/>
                <field name="qty"/>
                <button name="act" type="object" icon="fa-check"/>
            </list>
        </field>
    </form>
`;

test(`x2many: the row button stays out of the tab order across a handover`, async () => {
    await mountView({ resModel: "order", type: "form", resId: 1, arch: ARCH });
    await animationFrame();

    const tabindexes = () =>
        [...document.querySelectorAll(".o_data_row button[name=act]")]
            .slice(0, 6)
            .map((b) => b.getAttribute("tabindex"));

    expect(tabindexes()).toEqual(["0", "0", "0", "0", "0", "0"], {
        message: "nothing in edition: the row buttons are reachable by Tab",
    });

    await contains(`.o_data_row:eq(0) [name=name]`).click();
    await animationFrame();
    expect(tabindexes()).toEqual(["-1", "-1", "-1", "-1", "-1", "-1"], {
        message: "a line is in edition: every row button leaves the tab order",
    });

    const stats = await renderCounts(async () => {
        await contains(`.o_data_row:eq(2) [name=name]`).click();
        await animationFrame();
    });

    expect(`.o_data_row:eq(2)`).toHaveClass("o_selected_row");
    expect(tabindexes()).toEqual(["-1", "-1", "-1", "-1", "-1", "-1"], {
        message: "edition moved, not ended: the buttons stay out of the tab order",
    });
    expect(stats["list.ListRecordRow"] || 0).toBeLessThan(10, {
        message: `moving edition repainted ${stats["list.ListRecordRow"]} of 30 rows`,
    });
});
