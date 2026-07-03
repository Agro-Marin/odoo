// @ts-check

/**
 * @module tests/views/list/list_virtualization
 *
 * Regression guards for the list view row virtualization.
 *
 * V1 — stable row keys
 * --------------------
 * Virtualized rows must be keyed by stable identity (record id), not by
 * `flatRow.globalIndex`: inserting a row above (editable="top" New) shifts
 * every following globalIndex, and positional keys would tear down and
 * recreate every following row instead of patching them in place. The test
 * anchors on a `<tr>` DOM node by `data-id` and asserts the exact same node
 * survives the insertion.
 *
 * V2 — spacer/threshold behavior
 * ------------------------------
 * Above the activation threshold only a slice of rows is rendered, with a
 * spacer row absorbing the remaining height.
 */

import { expect, test } from "@odoo/hoot";
import { queryAll, queryFirst } from "@odoo/hoot-dom";
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
    name = fields.Char();
    _records = Array.from({ length: 150 }, (_, i) => ({
        id: i + 1,
        name: `record ${i + 1}`,
    }));
}

const { ResCompany, ResPartner, ResUsers } = webModels;

defineModels([Foo, ResCompany, ResPartner, ResUsers]);

test.tags("desktop");
test("virtualization renders a slice of rows plus a spacer (V2)", async () => {
    await mountView({
        resModel: "foo",
        type: "list",
        arch: `<list limit="200"><field name="name"/></list>`,
    });

    const rows = queryAll(".o_data_row");
    expect(rows.length).toBeGreaterThan(0);
    expect(rows.length).toBeLessThan(150);
    // Scrolled to the top: no top spacer, one bottom spacer.
    expect(".o_virtual_spacer").toHaveCount(1);
});

test.tags("desktop");
test("virtualized row DOM nodes survive an insertion above (V1)", async () => {
    await mountView({
        resModel: "foo",
        type: "list",
        arch: `<list editable="top" limit="200"><field name="name"/></list>`,
    });

    // Anchor an arbitrary rendered row by its stable data-id.
    const anchor = queryAll(".o_data_row")[2];
    const anchorId = anchor.dataset.id;
    expect(anchorId).not.toBe(undefined);

    // Insert a new record at the top: every following flat row's globalIndex
    // shifts by one.
    await contains(".o_list_button_add").click();
    await animationFrame();

    // The new edited row is present at the top…
    expect(".o_data_row.o_selected_row").toHaveCount(1);
    // …and the anchored row was patched in place: same DOM node, still
    // connected, same data-id.
    const after = queryFirst(`.o_data_row[data-id='${anchorId}']`);
    expect(after).toBe(anchor);
    expect(anchor.isConnected).toBe(true);
});
