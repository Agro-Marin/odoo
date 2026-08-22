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

class Foo extends models.Model {
    _name = "foo";
    foo = fields.Char();
    bar = fields.Boolean();

    _records = Array.from({ length: 12 }, (_, i) => ({
        id: i + 1,
        foo: `card ${i + 1}`,
        bar: i % 2 === 0,
    }));
}

defineModels([...Object.values(webModels), Foo]);

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
    <kanban>
        <templates>
            <t t-name="card">
                <field name="foo"/>
            </t>
        </templates>
    </kanban>
`;

test(`the card render counter is wired`, async () => {
    const stats = await renderCounts(async () => {
        await mountView({
            resModel: "foo",
            type: "kanban",
            groupBy: ["bar"],
            arch: ARCH,
        });
        await animationFrame();
    });

    expect(`.o_kanban_record`).toHaveCount(12);
    expect(stats["kanban.KanbanRecord"]).toBe(12, {
        message: "mounting 12 cards must be counted as 12 card renders",
    });
});

test(`opening the quick create repaints no card`, async () => {
    await mountView({ resModel: "foo", type: "kanban", groupBy: ["bar"], arch: ARCH });
    await animationFrame();

    const stats = await renderCounts(async () => {
        await contains(`.o_kanban_group:eq(0) .o_kanban_quick_add`).click();
        await animationFrame();
    });

    expect(`.o_kanban_quick_create`).toHaveCount(1);
    expect(stats["kanban.KanbanRecord"] || 0).toBe(0, {
        message: "the quick-create form is not a card and must not repaint any",
    });
});

test(`closing the quick create repaints no card`, async () => {
    await mountView({ resModel: "foo", type: "kanban", groupBy: ["bar"], arch: ARCH });
    await animationFrame();
    await contains(`.o_kanban_group:eq(0) .o_kanban_quick_add`).click();
    await animationFrame();

    const stats = await renderCounts(async () => {
        await contains(`.o_kanban_quick_create .o_kanban_cancel`).click();
        await animationFrame();
    });

    expect(`.o_kanban_quick_create`).toHaveCount(0);
    expect(stats["kanban.KanbanRecord"] || 0).toBe(0, {
        message: "dismissing the quick create must not repaint the cards either",
    });
});
