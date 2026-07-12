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
 *
 * V6 — inline edit × virtualization
 * Scrolling away from an inline-edited row must NOT extend the rendered
 * window up to that row (which would materialize every row in between): the
 * edited row is kept alive as a single island adjacent to the spacer, so
 * the rendered row count stays bounded and the pending edit survives.
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
    bar = fields.Char();
    category = fields.Char();
    _records = Array.from({ length: 150 }, (_, i) => ({
        id: i + 1,
        name: `record ${i + 1}`,
        bar: `bar ${i + 1}`,
        category: i < 3 ? "cat_a" : "cat_b",
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
test("edited row scrolled far away stays a bounded island (V6)", async () => {
    await mountView({
        resModel: "foo",
        type: "list",
        arch: `<list editable="bottom" limit="200"><field name="name"/></list>`,
    });

    // Enter edit on the first row and type a pending (unsaved) value.
    await contains(".o_data_row:first-child .o_data_cell").click();
    expect(".o_data_row.o_selected_row").toHaveCount(1);
    const editedId = queryFirst(".o_data_row.o_selected_row").dataset.id;
    await contains(".o_selected_row [name='name'] input").edit("pending edit", {
        confirm: false,
    });

    // Scroll far away from the edited row.
    await contains(".o_list_renderer").scroll({ top: 5000 });
    await animationFrame();
    await animationFrame();

    // The rendered slice must NOT span from the edited row to the viewport:
    // only the visible window plus the single edited-row island is rendered.
    const rows = queryAll(".o_data_row");
    expect(rows.length).toBeLessThan(100);

    // The edited row is still rendered (island adjacent to the top spacer),
    // still in edition, with its pending input intact.
    expect(".o_data_row.o_selected_row").toHaveCount(1);
    const island = queryFirst(".o_data_row.o_selected_row");
    expect(island.dataset.id).toBe(editedId);
    expect(island).toBe(rows[0]);
    expect(".o_selected_row [name='name'] input").toHaveValue("pending edit");

    // The rest of the window really is far away (no contiguous fill-in).
    expect(Number(rows[1].dataset.rowIndex)).toBeGreaterThan(50);

    // Scrolling back re-integrates the edited row into the window without
    // losing the edition.
    await contains(".o_list_renderer").scroll({ top: 0 });
    await animationFrame();
    await animationFrame();
    expect(".o_data_row.o_selected_row").toHaveCount(1);
    expect(".o_selected_row [name='name'] input").toHaveValue("pending edit");
});

test.tags("desktop");
test("grouped: arrow traversal crosses an 'Add a line' row without trapping focus (V7)", async () => {
    // Regression: an add-line row has at most two cells (selector placeholder
    // + one colspan cell, no data-col-index). Arriving on it from a record
    // column >= 2 made focusAtPosition return null for a RENDERED row, which
    // the virtualization path misread as "row scrolled out": viewport jump +
    // a pending focus that never resolved — ArrowDown wedged at every group
    // boundary of a virtualized grouped list.
    await mountView({
        resModel: "foo",
        type: "list",
        arch: `<list editable="bottom" expand="1" limit="200"><field name="name"/><field name="bar"/></list>`,
        groupBy: ["category"],
    });

    // Virtualization is active (154 flat rows) and the first group (cat_a,
    // 3 records) is fully rendered, including its add-line row.
    const groupRows = queryAll(".o_data_row");
    const lastCatARow = groupRows[2];
    const addLineCell = queryFirst("td.o_group_field_row_add");
    expect(addLineCell).not.toBe(null);

    // Focus the LAST column (colIndex 2: selector + name + bar) of the last
    // cat_a record, directly above the add-line row.
    const cell = lastCatARow.querySelector("[data-col-index='2']");
    cell.focus({ preventScroll: true });
    expect(cell).toBeFocused();

    // ArrowDown lands on the add-line row (clamped to its last cell)
    // instead of jumping the viewport and losing focus.
    await press("ArrowDown");
    await animationFrame();
    expect(document.activeElement.closest("td.o_group_field_row_add")).not.toBe(null);

    // Continuing down crosses the next group header and re-enters records
    // at the remembered column.
    await press("ArrowDown");
    await animationFrame();
    expect(document.activeElement.closest("tr.o_group_header")).not.toBe(null);

    await press("ArrowDown");
    await animationFrame();
    const focusedCell = document.activeElement.closest("[data-col-index]");
    expect(focusedCell).not.toBe(null);
    expect(focusedCell.dataset.colIndex).toBe("2");
    expect(document.activeElement.closest(".o_data_row")).not.toBe(null);
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
