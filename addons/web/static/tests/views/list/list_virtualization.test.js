// @ts-check

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
    expect(".o_virtual_spacer").toHaveCount(1);
});

test.tags("desktop");
test("virtualized row DOM nodes survive an insertion above (V1)", async () => {
    await mountView({
        resModel: "foo",
        type: "list",
        arch: `<list editable="top" limit="200"><field name="name"/></list>`,
    });

    const anchor = queryAll(".o_data_row")[2];
    const anchorId = anchor.dataset.id;
    expect(anchorId).not.toBe(undefined);

    await contains(".o_list_button_add").click();
    await animationFrame();

    expect(".o_data_row.o_selected_row").toHaveCount(1);
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

    await contains(".o_list_renderer").scroll({ top: 2000 });
    await animationFrame();

    const firstRendered = queryFirst(".o_data_row");
    const rowIndex = Number(firstRendered.dataset.rowIndex);
    expect(rowIndex).toBeGreaterThan(0);

    const cell = firstRendered.querySelector(".o_data_cell");
    cell.focus({ preventScroll: true });
    expect(cell).toBeFocused();

    await press("ArrowUp");
    expect(".o_searchview_input").not.toBeFocused();

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

    const lastRendered = queryAll(".o_data_row").at(-1);
    const rowIndex = Number(lastRendered.dataset.rowIndex);
    expect(rowIndex).toBeLessThan(149);

    const cell = lastRendered.querySelector(".o_data_cell");
    cell.focus({ preventScroll: true });
    expect(cell).toBeFocused();

    const leakedKeydowns = [];
    const onKeydown = (ev) => leakedKeydowns.push(ev.key);
    document.addEventListener("keydown", onKeydown);
    await press("ArrowDown");
    document.removeEventListener("keydown", onKeydown);
    expect(leakedKeydowns).toEqual([]);
    expect(".o_searchview_input").not.toBeFocused();

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

    await contains(".o_data_row:first-child .o_data_cell").click();
    expect(".o_data_row.o_selected_row").toHaveCount(1);
    const editedId = queryFirst(".o_data_row.o_selected_row").dataset.id;
    await contains(".o_selected_row [name='name'] input").edit("pending edit", {
        confirm: false,
    });

    await contains(".o_list_renderer").scroll({ top: 5000 });
    await animationFrame();
    await animationFrame();

    const rows = queryAll(".o_data_row");
    expect(rows.length).toBeLessThan(100);

    expect(".o_data_row.o_selected_row").toHaveCount(1);
    const island = queryFirst(".o_data_row.o_selected_row");
    expect(island.dataset.id).toBe(editedId);
    expect(island).toBe(rows[0]);
    expect(".o_selected_row [name='name'] input").toHaveValue("pending edit");

    expect(Number(rows[1].dataset.rowIndex)).toBeGreaterThan(50);

    await contains(".o_list_renderer").scroll({ top: 0 });
    await animationFrame();
    await animationFrame();
    expect(".o_data_row.o_selected_row").toHaveCount(1);
    expect(".o_selected_row [name='name'] input").toHaveValue("pending edit");
});

test.tags("desktop");
test("grouped: arrow traversal crosses an 'Add a line' row without trapping focus (V7)", async () => {
    await mountView({
        resModel: "foo",
        type: "list",
        arch: `<list editable="bottom" expand="1" limit="200"><field name="name"/><field name="bar"/></list>`,
        groupBy: ["category"],
    });

    const groupRows = queryAll(".o_data_row");
    const lastCatARow = groupRows[2];
    const addLineCell = queryFirst("td.o_group_field_row_add");
    expect(addLineCell).not.toBe(null);

    const cell = lastCatARow.querySelector("[data-col-index='2']");
    cell.focus({ preventScroll: true });
    expect(cell).toBeFocused();

    await press("ArrowDown");
    await animationFrame();
    expect(document.activeElement.closest("td.o_group_field_row_add")).not.toBe(null);

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

    await press("ArrowUp");
    await animationFrame();
    expect(".o_searchview_input").not.toBeFocused();
    expect(document.activeElement.closest("thead")).not.toBe(null);

    await press("ArrowUp");
    await animationFrame();
    expect(".o_searchview_input").toBeFocused();
});

test.tags("mobile");
test("virtualization engages on small screens too (V8)", async () => {
    await mountView({
        resModel: "foo",
        type: "list",
        arch: `<list limit="200"><field name="name"/></list>`,
    });

    const rows = queryAll(".o_data_row");
    expect(rows.length).toBeGreaterThan(0);
    expect(rows.length).toBeLessThan(150);
    expect(".o_virtual_spacer").toHaveCount(1);
});

test.tags("mobile");
test("every row stays reachable by scrolling on small screens (V9)", async () => {
    await mountView({
        resModel: "foo",
        type: "list",
        arch: `<list limit="200"><field name="name"/></list>`,
    });

    const renderer = queryFirst(".o_list_renderer");
    const scrollable = new Set(["auto", "scroll", "overlay"]);
    let scroller = renderer;
    for (let node = renderer; node; node = node.parentElement) {
        if (
            node.scrollHeight > node.clientHeight &&
            scrollable.has(getComputedStyle(node).overflowY)
        ) {
            scroller = node;
            break;
        }
    }
    expect(scroller).not.toBe(renderer);

    scroller.scrollTop = scroller.scrollHeight;
    await animationFrame();
    await animationFrame();

    const names = queryAll(".o_data_row .o_data_cell").map((td) =>
        td.textContent.trim(),
    );
    expect(names.at(-1)).toBe("record 150");
});

test.tags("desktop");
test("a short list does no ancestor style walk on patch", async () => {
    await mountView({
        resModel: "foo",
        type: "list",
        arch: `<list limit="5"><field name="name"/></list>`,
    });
    await animationFrame();

    const real = window.getComputedStyle;
    /** @type {string[]} */
    const walked = [];
    window.getComputedStyle = function (el, ...rest) {
        if (el === document.documentElement) {
            walked.push(el.tagName);
        }
        return real.call(this, el, ...rest);
    };
    try {
        await contains(`th[data-name=name]`).click();
        await animationFrame();
    } finally {
        window.getComputedStyle = real;
    }
    expect(walked).toEqual([]);
});

test.tags("desktop");
test("crossing the threshold still resolves the scroll container", async () => {
    await mountView({
        resModel: "foo",
        type: "list",
        arch: `<list limit="200"><field name="name"/></list>`,
        groupBy: ["category"],
    });
    await animationFrame();
    expect(".o_virtual_spacer").toHaveCount(0);

    await contains(".o_group_header:last-child").click();
    await animationFrame();

    expect(".o_virtual_spacer").toHaveCount(1);
    const firstIndex = Number(queryFirst(".o_data_row").dataset.rowIndex);

    await contains(".o_list_renderer").scroll({ top: 3000 });
    await animationFrame();
    await animationFrame();

    expect(Number(queryFirst(".o_data_row").dataset.rowIndex)).toBeGreaterThan(
        firstIndex,
    );
    expect(queryAll(".o_data_row").length).toBeLessThan(150);
});
