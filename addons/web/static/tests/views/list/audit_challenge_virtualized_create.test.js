// @ts-check

/**
 * AUDIT CHALLENGE — the virtualized row path drops the x2many "Add a line" row.
 *
 * `web.ListRenderer.Rows` is two hand-maintained branches: the virtualized one
 * renders only `virt.visibleFlatRows` plus spacers, while the create-controls
 * `<tr t-if="displayRowCreates">` — carrying the "Add a line" link and every
 * arch `<control>` button — exists ONLY in the non-virtualized `t-else`.
 *
 * `displayRowCreates` is `isX2Many && canCreate`, so this hits a one2many
 * inside a form: past the virtualization threshold (and with no handle field,
 * which would disable virtualization via `canResequence()`), the only
 * affordance for adding a line disappears.
 *
 * Grouped lists are unaffected — their add-line row is materialized by
 * `ListGridState` as a flat row (see V7 in list_virtualization.test.js) — which
 * is why this went unnoticed.
 *
 * Engaging the virtualized branch requires a bounded viewport. `useVirtualGrid`
 * reads its span from `scrollableRef.el.clientHeight`, and an x2many's
 * `.o_list_renderer` grows to fit its content (the form is the scroller), so
 * that span equals the content and every row falls inside the window. The
 * height cap below is what makes `.o_list_renderer` a real viewport, and hence
 * what keeps this guard pointed at the virtualized branch rather than the
 * `t-else`. See `list_virtualization_x2many.test.js` for the reachability
 * consequences of the unbounded case.
 */

import { expect, test } from "@odoo/hoot";
import {
    defineModels,
    fields,
    models,
    mountView,
    webModels,
} from "@web/../tests/web_test_helpers";

class Parent extends models.Model {
    name = fields.Char();
    line_ids = fields.One2many({ relation: "line" });
    _records = [{ id: 1, name: "parent", line_ids: [] }];
}

class Line extends models.Model {
    name = fields.Char();
    parent_id = fields.Many2one({ relation: "parent" });
    _records = [];
}

const { ResCompany, ResPartner, ResUsers } = webModels;
defineModels([Parent, Line, ResCompany, ResPartner, ResUsers]);

/** @param {number} count */
function seedLines(count) {
    Line._records = Array.from({ length: count }, (_, i) => ({
        id: i + 1,
        name: `line ${i + 1}`,
        parent_id: 1,
    }));
    Parent._records[0].line_ids = Line._records.map((r) => r.id);
}

const ARCH = `
    <form>
        <field name="line_ids">
            <list editable="bottom" limit="200"><field name="name"/></list>
        </field>
    </form>`;

test.tags("desktop");
test("x2many below the virtualization threshold shows 'Add a line' (control)", async () => {
    seedLines(5);
    await mountView({ resModel: "parent", type: "form", resId: 1, arch: ARCH });

    expect(".o_virtual_spacer").toHaveCount(0);
    expect(".o_field_x2many_list_row_add").toHaveCount(1);
});

/** Cap the x2many list to a real viewport so virtualization can engage. */
function capListViewport(px) {
    const style = document.createElement("style");
    style.textContent = `.o_field_x2many .o_list_renderer {
        height: ${px}px !important;
        max-height: ${px}px !important;
        overflow-y: auto !important;
    }`;
    document.head.appendChild(style);
    return () => style.remove();
}

test.tags("desktop");
test("x2many above the virtualization threshold still shows 'Add a line'", async () => {
    const restore = capListViewport(300);
    try {
        seedLines(150);
        await mountView({ resModel: "parent", type: "form", resId: 1, arch: ARCH });

        expect(".o_virtual_spacer").toHaveCount(1);
        expect(".o_field_x2many_list_row_add").toHaveCount(1);
    } finally {
        restore();
    }
});
