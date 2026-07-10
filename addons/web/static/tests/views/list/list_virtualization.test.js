// @ts-check

/**
 * @module tests/views/list/list_virtualization
 *
 * Regression guards for the list view row virtualization.
 *
 * V1 — stable row keys
 * Virtualized rows must be keyed by stable identity (record id), not by
 * `flatRow.globalIndex`: inserting a row above (editable="top" New) shifts
 * every following globalIndex, and positional keys would tear down and
 * recreate every following row instead of patching them in place. The test
 * anchors on a `<tr>` DOM node by `data-id` and asserts the exact same node
 * survives the insertion.
 *
 * V2 — spacer/threshold behavior
 * Above the activation threshold only a slice of rows is rendered, with a
 * spacer row absorbing the remaining height.
 *
 * V3/V4/V5 — keyboard navigation × virtualization
 * When an arrow key targets a row that exists but is virtualized out of the
 * DOM, the nav hook arms a pending focus (resolved after the next patch) and
 * must consume the event: the "grid boundary" fallbacks (focus the search
 * bar on ArrowUp, default browser scroll on ArrowDown) must not fire while
 * that focus move is in flight (V3, V4). The true boundary behavior — ArrowUp
 * from the header row focuses the search bar — is preserved (V5).
 */

import { expect, test } from "@odoo/hoot";
import { press, queryAll, queryFirst, waitFor } from "@odoo/hoot-dom";
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

test.tags("desktop");
test("ArrowUp at the top rendered edge does not focus the search bar (V3)", async () => {
    await mountView({
        resModel: "foo",
        type: "list",
        arch: `<list limit="200"><field name="name"/></list>`,
    });

    // Shift the virtualization window down so the first rendered row is
    // not the first record of the list.
    await contains(".o_list_renderer").scroll({ top: 2000 });
    await animationFrame();

    const firstRendered = queryFirst(".o_data_row");
    const rowIndex = Number(firstRendered.dataset.rowIndex);
    expect(rowIndex).toBeGreaterThan(0);

    const cell = firstRendered.querySelector(".o_data_cell");
    cell.focus({ preventScroll: true });
    expect(cell).toBeFocused();

    await press("ArrowUp");
    // The target row exists (it is only virtualized out): the search bar
    // must not transiently steal focus while the window shifts.
    expect(".o_searchview_input").not.toBeFocused();

    // The window scrolls, re-renders, and the pending focus resolves on
    // the previous row.
    await waitFor(`.o_data_row[data-row-index='${rowIndex - 1}']`);
    await animationFrame();
    expect(".o_searchview_input").not.toBeFocused();
    expect(
        queryFirst(`.o_data_row[data-row-index='${rowIndex - 1}'] .o_data_cell`),
    ).toBeFocused();
});

test.tags("desktop");
test("ArrowDown at the bottom rendered edge focuses the next row (V4)", async () => {
    await mountView({
        resModel: "foo",
        type: "list",
        arch: `<list limit="200"><field name="name"/></list>`,
    });

    // Scrolled to the top: the last rendered row is not the last record.
    const lastRendered = queryAll(".o_data_row").at(-1);
    const rowIndex = Number(lastRendered.dataset.rowIndex);
    expect(rowIndex).toBeLessThan(149);

    const cell = lastRendered.querySelector(".o_data_cell");
    cell.focus({ preventScroll: true });
    expect(cell).toBeFocused();

    // When the nav hook handles a key, the renderer calls preventDefault()
    // and stopPropagation(): a bubble listener at document level only sees
    // the keydown when the event was NOT consumed (which would trigger the
    // default browser scroll while the pending focus is in flight).
    const leakedKeydowns = [];
    const onKeydown = (ev) => leakedKeydowns.push(ev.key);
    document.addEventListener("keydown", onKeydown);
    await press("ArrowDown");
    document.removeEventListener("keydown", onKeydown);
    expect(leakedKeydowns).toEqual([]);
    expect(".o_searchview_input").not.toBeFocused();

    // The window scrolls, re-renders, and the pending focus resolves on
    // the next row.
    await waitFor(`.o_data_row[data-row-index='${rowIndex + 1}']`);
    await animationFrame();
    expect(
        queryFirst(`.o_data_row[data-row-index='${rowIndex + 1}'] .o_data_cell`),
    ).toBeFocused();
});

test.tags("desktop");
test("ArrowUp from the true first row still reaches the search bar (V5)", async () => {
    await mountView({
        resModel: "foo",
        type: "list",
        arch: `<list limit="200"><field name="name"/></list>`,
    });

    const firstRow = queryFirst(".o_data_row");
    expect(Number(firstRow.dataset.rowIndex)).toBe(0);

    const cell = firstRow.querySelector(".o_data_cell");
    cell.focus({ preventScroll: true });

    // First ArrowUp: grid boundary for data rows — focus moves into the
    // header row, not the search bar.
    await press("ArrowUp");
    await animationFrame();
    expect(".o_searchview_input").not.toBeFocused();
    expect(document.activeElement.closest("thead")).not.toBe(null);

    // Second ArrowUp: real top-of-grid boundary — the search bar takes focus.
    await press("ArrowUp");
    await animationFrame();
    expect(".o_searchview_input").toBeFocused();
});
