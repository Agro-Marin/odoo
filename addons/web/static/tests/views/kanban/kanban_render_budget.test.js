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
 * Render counts by component label, for one workload. Uses the
 * `useRenderCounter` instrumentation the components already carry
 * (`core/utils/render_instrumentation.js`) rather than patching prototypes, so
 * a budget assertion stays readable and does not depend on component
 * internals.
 *
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

// Positive control. Both budgets below assert a count of ZERO, which is also
// what a renamed or removed `useRenderCounter("kanban.KanbanRecord")` label
// would report -- the assertions would keep passing while measuring nothing.
// This pins that the label is wired and really counts cards.
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

// A blanket `render(true)` on every model update used to repaint every card
// for any change, and removing it is what made per-card subscriptions load
// bearing (see tooling/architecture/js_forced_render.py). These pin the
// consequence: an interaction that concerns no card must repaint no card.
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
