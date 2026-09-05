// @ts-check

import { expect, test } from "@odoo/hoot";
import { queryOne } from "@odoo/hoot-dom";
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
    color = fields.Integer();
    _records = [{ id: 1, name: "t1", color: 3 }];
}

class Msg extends models.Model {
    _name = "msg";
    name = fields.Char();
    res_model = fields.Char();
    res_id = fields.Many2oneReference({ model_field: "res_model", relation: "tag" });
    _records = [{ id: 1, name: "m", res_model: "tag", res_id: 1 }];
}

class Partner extends models.Model {
    name = fields.Char();
    other = fields.Char();
    flag = fields.Boolean();
    tag_id = fields.Many2one({ relation: "tag" });
    tag_ids = fields.Many2many({ relation: "tag" });
    line_ids = fields.One2many({ relation: "line", relation_field: "partner_id" });
    ref = fields.Reference({ selection: [["tag", "Tag"]] });
    _records = [
        {
            id: 1,
            name: "p",
            other: "o",
            flag: false,
            tag_id: 1,
            tag_ids: [1],
            line_ids: [1, 2],
            ref: "tag,1",
        },
    ];
}

class Line extends models.Model {
    _name = "line";
    name = fields.Char();
    other = fields.Char();
    partner_id = fields.Many2one({ relation: "partner" });
    _records = [
        { id: 1, name: "l1", other: "o1", partner_id: 1 },
        { id: 2, name: "l2", other: "o2", partner_id: 1 },
    ];
}

class ResUsers extends models.Model {
    _name = "res.users";
    has_group() {
        return true;
    }
}

defineModels([Partner, Tag, Msg, Line, ResUsers]);

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

/** Five committed edits of an unrelated char field on the same record. */
async function editUnrelatedFiveTimes() {
    for (const value of ["x", "xy", "xyz", "xyza", "xyzab"]) {
        await contains("[name='name'] input").edit(value);
        await animationFrame();
    }
}

/**
 * Mounts inside a traced window, so the caller can assert the counter it is
 * about to expect a zero from was non-zero here. Without that control, every
 * "renders 0 times" assertion below would also pass if the widget never mounted,
 * or if the counter were dropped from the component.
 *
 * @param {Parameters<typeof mountView>[0]} params
 * @returns {Promise<Record<string, number>>}
 */
function mountCounting(params) {
    return renderCounts(async () => {
        await mountView(params);
        await animationFrame();
    });
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

    const stats = await renderCounts(editUnrelatedFiveTimes);

    expect(stats["fields.CharField"]).toBe(5);
    expect(stats["fields.Many2ManyTagsField"]).toBe(5);
});

test("many2one does not re-render its autocomplete on an unrelated edit", async () => {
    const mounted = await mountCounting({
        type: "form",
        resModel: "partner",
        resId: 1,
        arch: `<form><field name="name"/><field name="tag_id"/></form>`,
    });
    expect(mounted["fields.Many2One"]).toBeGreaterThan(0);
    expect("[name='tag_id'] input").toHaveValue("t1");

    const stats = await renderCounts(editUnrelatedFiveTimes);

    expect(stats["fields.CharField"]).toBe(5);
    expect(stats["fields.Many2One"] || 0).toBe(0);
});

test("reference does not re-render its autocomplete on an unrelated edit", async () => {
    const mounted = await mountCounting({
        type: "form",
        resModel: "partner",
        resId: 1,
        arch: `<form><field name="name"/><field name="ref"/></form>`,
    });
    expect(mounted["fields.Many2One"]).toBeGreaterThan(0);
    expect("[name='ref'] input.o_input").toHaveCount(1);

    const stats = await renderCounts(editUnrelatedFiveTimes);

    expect(stats["fields.CharField"]).toBe(5);
    expect(stats["fields.Many2One"] || 0).toBe(0);
});

test("many2one_reference does not re-render its autocomplete on an unrelated edit", async () => {
    const mounted = await mountCounting({
        type: "form",
        resModel: "msg",
        resId: 1,
        arch: `
            <form>
                <field name="name"/>
                <field name="res_model" invisible="1"/>
                <field name="res_id" widget="many2one_reference"/>
            </form>`,
    });
    expect(mounted["fields.Many2One"]).toBeGreaterThan(0);
    expect("[name='res_id'] input").toHaveValue("t1");

    const stats = await renderCounts(editUnrelatedFiveTimes);

    expect(stats["fields.CharField"]).toBe(5);
    expect(stats["fields.Many2One"] || 0).toBe(0);
});

test("many2many_tags does not re-render its tag list on an unrelated edit", async () => {
    const mounted = await mountCounting({
        type: "form",
        resModel: "partner",
        resId: 1,
        arch: `<form><field name="name"/><field name="tag_ids" widget="many2many_tags"/></form>`,
    });
    expect(mounted["components.TagsList"]).toBeGreaterThan(0);
    expect(".o_field_tags .o_tag").toHaveCount(1);

    const stats = await renderCounts(editUnrelatedFiveTimes);

    expect(stats["fields.CharField"]).toBe(5);
    expect(stats["components.TagsList"] || 0).toBe(0);
});

// The x2many field itself re-renders with its record, which is expected; what
// must not happen is that render reaching the sub-view. It did: `rendererProps`
// bound `openRecord` afresh and built `nestedKeyOptionalFieldsData` (list) or
// the draggable-patched `archInfo` (kanban) as a new object every render, so
// OWL saw changed props and re-rendered the whole list -- every row -- for an
// edit of an unrelated char field on the parent. The sub-view still follows its
// own records through reactivity, so nothing it shows depends on this render.
test("x2many list does not re-render its sub-view on an unrelated edit", async () => {
    const mounted = await mountCounting({
        type: "form",
        resModel: "partner",
        resId: 1,
        arch: `
            <form>
                <field name="name"/>
                <field name="line_ids">
                    <list><field name="name"/></list>
                </field>
            </form>`,
    });
    expect(mounted["list.ListRenderer"]).toBeGreaterThan(0);
    expect(".o_field_x2many_list .o_data_row").toHaveCount(2);

    const stats = await renderCounts(editUnrelatedFiveTimes);

    expect(stats["fields.CharField"]).toBe(5);
    expect(stats["list.ListRenderer"] || 0).toBe(0);
    expect(stats["list.ListRecordRow"] || 0).toBe(0);
});

test("x2many kanban does not re-render its sub-view on an unrelated edit", async () => {
    const mounted = await mountCounting({
        type: "form",
        resModel: "partner",
        resId: 1,
        arch: `
            <form>
                <field name="name"/>
                <field name="line_ids">
                    <kanban><t t-name="card"><field name="name"/></t></kanban>
                </field>
            </form>`,
    });
    expect(mounted["kanban.KanbanRenderer"]).toBeGreaterThan(0);
    expect(".o_field_x2many_kanban .o_kanban_record:contains(l1)").toHaveCount(1);
    expect(".o_field_x2many_kanban .o_kanban_record:contains(l2)").toHaveCount(1);

    const stats = await renderCounts(editUnrelatedFiveTimes);

    expect(stats["fields.CharField"]).toBe(5);
    expect(stats["kanban.KanbanRenderer"] || 0).toBe(0);
    expect(stats["kanban.KanbanRecord"] || 0).toBe(0);
});

// What the two tests above rely on: a sub-view modifier that reads `parent.*`
// must still follow the parent, now that the parent's render no longer reaches
// the sub-view. It does, through reactivity on the parent record's data; this
// is the control that says the zeros above are not a sub-view frozen in place.
test("x2many sub-view modifiers reading parent still follow the parent", async () => {
    await mountView({
        type: "form",
        resModel: "partner",
        resId: 1,
        arch: `
            <form>
                <field name="flag"/>
                <field name="line_ids">
                    <list editable="bottom">
                        <field name="name" readonly="parent.flag"/>
                        <field name="other" column_invisible="parent.flag"/>
                    </list>
                </field>
            </form>`,
    });
    await animationFrame();
    expect(".o_field_x2many_list th[data-name]").toHaveCount(2);
    expect(".o_data_row .o_data_cell.o_readonly_modifier").toHaveCount(0);

    await contains("[name='flag'] input").click();
    await animationFrame();

    expect(".o_field_x2many_list th[data-name]").toHaveCount(1);
    expect(".o_data_row .o_data_cell.o_readonly_modifier").toHaveCount(2);
});

test("x2many kanban card modifiers reading parent still follow the parent", async () => {
    await mountView({
        type: "form",
        resModel: "partner",
        resId: 1,
        arch: `
            <form>
                <field name="flag"/>
                <field name="line_ids">
                    <kanban>
                        <t t-name="card">
                            <field name="name"/>
                            <span class="o_probe" invisible="parent.flag">X</span>
                        </t>
                    </kanban>
                </field>
            </form>`,
    });
    await animationFrame();
    expect(".o_kanban_record .o_probe").toHaveCount(2);

    await contains("[name='flag'] input").click();
    await animationFrame();

    expect(".o_kanban_record .o_probe").toHaveCount(0);
});

// Each toggle saves, and the save reloads the x2many, so its record objects are
// new every time and the tag props genuinely change once per toggle. What the
// memo removes is the *second* render per toggle: the card renders twice (the
// optimistic value, then the reloaded one) and only one of those changes a tag.
// The Many2ManyTagsField count is the control -- it is what says the card really
// did render twice, so `TagsList: 5` is a halving and not an absence.
test("kanban many2many_tags re-renders its tag list once per save, not per render", async () => {
    const mounted = await mountCounting({
        type: "kanban",
        resModel: "partner",
        arch: `
            <kanban>
                <templates>
                    <t t-name="card">
                        <field name="flag" widget="boolean_toggle"/>
                        <field name="tag_ids" widget="many2many_tags" options="{'color_field': 'color'}"/>
                    </t>
                </templates>
            </kanban>`,
    });
    expect(mounted["components.TagsList"]).toBeGreaterThan(0);
    expect(".o_kanban_record .o_tag").toHaveCount(1);

    const stats = await renderCounts(async () => {
        for (let i = 0; i < 5; i++) {
            await contains("[name='flag'] input").click();
            await animationFrame();
        }
    });

    expect(stats["fields.Many2ManyTagsField"]).toBe(10);
    expect(stats["components.TagsList"]).toBe(5);
});

// The tag list is keyed by `resId`, not by the datapoint id `getTagProps` puts
// in `id`. Keyed on the latter, a save re-minted the key and OWL destroyed and
// rebuilt every tag's DOM node although nothing about the tag had changed.
test("a save does not rebuild the tag DOM nodes", async () => {
    await mountView({
        type: "kanban",
        resModel: "partner",
        arch: `
            <kanban>
                <templates>
                    <t t-name="card">
                        <field name="flag" widget="boolean_toggle"/>
                        <field name="tag_ids" widget="many2many_tags" options="{'color_field': 'color'}"/>
                    </t>
                </templates>
            </kanban>`,
    });
    await animationFrame();

    const before = queryOne(".o_kanban_record .o_tag");
    expect(before).toHaveCount(1);
    before.dataset.probeMark = "sentinel";

    await contains("[name='flag'] input").click();
    await animationFrame();

    const after = queryOne(".o_kanban_record .o_tag");
    expect(after).toBe(before);
    expect(after.dataset.probeMark).toBe("sentinel");
});
