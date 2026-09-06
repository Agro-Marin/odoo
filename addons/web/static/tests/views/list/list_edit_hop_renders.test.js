// @ts-check
import { expect, test } from "@odoo/hoot";
import { queryAll } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { onWillRender } from "@odoo/owl";
import {
    contains,
    defineModels,
    fields,
    models,
    mountView,
    patchWithCleanup,
    webModels,
} from "@web/../tests/web_test_helpers";
import { ListRecordRow } from "@web/views/list/list_record_row";

class Partner extends models.Model {
    name = fields.Char();
    parent_id = fields.Many2one({ relation: "partner" });
    tag_ids = fields.Many2many({ relation: "tag" });
    _records = Array.from({ length: 6 }, (_, i) => ({
        id: i + 1,
        name: `p${i + 1}`,
        parent_id: i ? 1 : false,
        tag_ids: [1, 2],
    }));
}
class Tag extends models.Model {
    name = fields.Char();
    _records = [
        { id: 1, name: "t1" },
        { id: 2, name: "t2" },
    ];
}
defineModels([...Object.values(webModels), Partner, Tag]);

const ARCH = `
    <list editable="bottom">
        <field name="name"/>
        <field name="parent_id"/>
        <field name="tag_ids" widget="many2many_tags"/>
    </list>`;

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

test("typing in an editable cell renders nothing until the value is committed", async () => {
    await mountView({ resModel: "partner", type: "list", arch: ARCH });
    await contains(".o_data_row:eq(1) [name=name]").click();
    await animationFrame();
    const stats = await renderCounts(async () => {
        await contains(".o_selected_row [name=name] input").edit("typed", {
            confirm: false,
        });
        await animationFrame();
    });
    expect(Object.keys(stats)).toEqual([]);
});

test("an Enter hand-over repaints the two rows involved and no other", async () => {
    /** @type {Record<string, number>} */
    const rowRenders = {};
    patchWithCleanup(ListRecordRow.prototype, {
        setup() {
            super.setup();
            onWillRender(() => {
                const id = this.props.record.resId;
                rowRenders[id] = (rowRenders[id] || 0) + 1;
            });
        },
    });
    await mountView({ resModel: "partner", type: "list", arch: ARCH });
    await contains(".o_data_row:eq(1) [name=name]").click();
    await animationFrame();
    for (const key of Object.keys(rowRenders)) {
        delete rowRenders[key];
    }
    const stats = await renderCounts(async () => {
        await contains(".o_selected_row [name=name] input").edit("v1");
        await animationFrame();
    });
    expect(queryAll(".o_selected_row [name=name] input")).toHaveCount(1);
    expect(Object.keys(rowRenders).sort()).toEqual(["2", "3"], {
        message: `rows repainted: ${JSON.stringify(rowRenders)}`,
    });
    expect(stats["list.ListRecordRow"]).toBeLessThan(8, {
        message: `row renders: ${stats["list.ListRecordRow"]}`,
    });
    expect(stats["list.ListRenderer"]).toBeLessThan(5, {
        message: `renderer renders: ${stats["list.ListRenderer"]}`,
    });
});
