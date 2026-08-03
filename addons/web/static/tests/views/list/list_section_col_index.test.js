// @ts-check

/**
 * @module tests/views/list/list_section_col_index
 *
 * ``ListRenderer.getColumns(record)`` is an override seam: the section
 * renderers (account/sale order lines, resource, survey, website_slides)
 * collapse a "section" row down to a handle + title pair, so such a row renders
 * a SUBSET of the grid's columns. Index-based keyboard navigation
 * (``ListGridState``) addresses the grid, so the ``data-col-index`` a cell
 * carries must be the column's canonical position in the full column set — not
 * its position within the row it happens to be rendered in.
 */

import { expect, test } from "@odoo/hoot";
import { queryAll } from "@odoo/hoot-dom";
import {
    defineModels,
    defineParams,
    fields,
    findComponent,
    models,
    mountView,
    webModels,
} from "@web/../tests/web_test_helpers";
import { registry } from "@web/core/registry";

class Foo extends models.Model {
    name = fields.Char();
    display_type = fields.Char();
    product = fields.Char();
    qty = fields.Integer();
    price = fields.Integer();

    _records = [
        {
            id: 1,
            display_type: "line_section",
            name: "SECTION",
            product: "",
            qty: 0,
            price: 0,
        },
        {
            id: 2,
            display_type: false,
            name: "line a",
            product: "xphone",
            qty: 2,
            price: 10,
        },
        {
            id: 3,
            display_type: false,
            name: "line b",
            product: "xpad",
            qty: 3,
            price: 20,
        },
    ];
}

const { ResCompany, ResPartner, ResUsers } = webModels;

defineModels([Foo, ResCompany, ResPartner, ResUsers]);

/**
 * Register a ``section_col_index_list`` js_class whose renderer narrows section
 * rows to [product, name] — mirroring what ``getSectionColumns`` does in
 * account/resource/survey/website_slides (filtered subset, title spread into a
 * clone carrying a colspan).
 */
function setupSectionList() {
    const listView = registry.category("views").get("list");
    class SectionListRenderer extends listView.Renderer {
        isSection(record) {
            return record.data.display_type === "line_section";
        }
        getColumns(record) {
            const columns = super.getColumns(record);
            if (!this.isSection(record)) {
                return columns;
            }
            const kept = columns.filter(
                (col) => col.name === "product" || col.name === "name",
            );
            return kept.map((col) =>
                col.name === "name" ? { ...col, colspan: 3 } : col,
            );
        }
    }
    registry
        .category("views")
        .add(
            "section_col_index_list",
            { ...listView, Renderer: SectionListRenderer },
            { force: true },
        );
}

// ``display_type`` drives isSection() but is not a column: declared
// column_invisible so it lands in record.data without joining ``columns``.
const ARCH = `
    <list js_class="section_col_index_list">
        <field name="display_type" column_invisible="1"/>
        <field name="product"/>
        <field name="qty"/>
        <field name="name"/>
        <field name="price"/>
    </list>`;

// this list renders a record selector, so grid column N sits at data-col-index
// N + 1 (see ListGridState#getColIndexOfColumn).
const SELECTOR_OFFSET = 1;

/** @param {HTMLElement} row */
function colIndexesOf(row) {
    return [...row.querySelectorAll("[data-col-index]")].map((cell) =>
        Number(cell.getAttribute("data-col-index")),
    );
}

test.tags("desktop");
test("a full row's cells carry their column's grid index", async () => {
    setupSectionList();
    await mountView({ resModel: "foo", type: "list", arch: ARCH });

    const fullRow = queryAll(".o_data_row")[1];
    expect(colIndexesOf(fullRow)).toEqual([0, 1, 2, 3].map((i) => i + SELECTOR_OFFSET));
});

test.tags("desktop");
test("a section row's narrowed cells keep their canonical grid index", async () => {
    setupSectionList();
    await mountView({ resModel: "foo", type: "list", arch: ARCH });

    const sectionRow = queryAll(".o_data_row")[0];
    // product is column 0 and name is column 2 of the grid. Numbering the two
    // rendered cells 0,1 — their position within this row — is what made an
    // arrow key leaving a section row land on the wrong column.
    expect(colIndexesOf(sectionRow)).toEqual([0, 2].map((i) => i + SELECTOR_OFFSET));
});

test.tags("desktop");
test("a vertical move out of a section row stays on the same grid column", async () => {
    setupSectionList();
    const view = await mountView({ resModel: "foo", type: "list", arch: ARCH });

    const renderer = findComponent(view, (component) => Boolean(component?.gridState));
    expect(Boolean(renderer)).toBe(true);

    const sectionRow = queryAll(".o_data_row")[0];
    const titleCell = sectionRow.querySelector(
        `[data-col-index='${2 + SELECTOR_OFFSET}']`,
    );
    expect(Boolean(titleCell)).toBe(true);

    const rowIndex = Number(sectionRow.getAttribute("data-row-index"));
    const move = renderer.gridState.moveFocus(
        rowIndex,
        Number(titleCell.getAttribute("data-col-index")),
        "down",
    );
    // the "name" column, not whatever sits at the title cell's within-row slot
    const targetRow = queryAll(".o_data_row")[1];
    const targetCell = targetRow.querySelector(`[data-col-index='${move.colIndex}']`);
    expect(targetCell.getAttribute("name")).toBe("name");
});

test.tags("desktop");
test("a horizontal move inside a narrowed row reaches the previous rendered cell", async () => {
    setupSectionList();
    const view = await mountView({ resModel: "foo", type: "list", arch: ARCH });
    const renderer = findComponent(view, (component) => Boolean(component?.gridState));

    const sectionRow = queryAll(".o_data_row")[0];
    const present = colIndexesOf(sectionRow);
    // product (0) and name (2) are rendered; grid column 1 (qty) is not.
    expect(present).toEqual([0, 2].map((i) => i + SELECTOR_OFFSET));

    const titleCell = sectionRow.querySelector(
        `[data-col-index='${2 + SELECTOR_OFFSET}']`,
    );
    const move = renderer.nav.findFocusMove(titleCell, false, "left");
    const landed = move.el.closest("[data-col-index]");
    // stepping left off column 2 must not dead-end on the column-1 hole
    expect(landed.getAttribute("data-col-index")).toBe(String(0 + SELECTOR_OFFSET));
});

test.tags("desktop");
test("RTL: a horizontal move inside a narrowed row follows index space, not the key", async () => {
    // Under RTL, ListGridState swaps left/right internally, so the key pressed
    // does not name the direction the column INDEX travels. findFocusMove
    // therefore derives the index-space direction from the move the grid
    // actually made; deriving it from the key would search the wrong way and
    // dead-end on the hole at column 1.
    defineParams({ lang_parameters: { direction: "rtl" } });
    setupSectionList();
    const view = await mountView({ resModel: "foo", type: "list", arch: ARCH });
    const renderer = findComponent(view, (component) => Boolean(component?.gridState));
    expect(renderer.gridState.isRTL).toBe(true);

    const sectionRow = queryAll(".o_data_row")[0];
    expect(colIndexesOf(sectionRow)).toEqual([0, 2].map((i) => i + SELECTOR_OFFSET));

    // pressing "left" under RTL moves the index RIGHT: 1 -> 2 (a hole) -> 3
    const handleCell = sectionRow.querySelector(
        `[data-col-index='${0 + SELECTOR_OFFSET}']`,
    );
    const move = renderer.nav.findFocusMove(handleCell, false, "left");
    const landed = move.el.closest("[data-col-index]");
    expect(landed.getAttribute("data-col-index")).toBe(String(2 + SELECTOR_OFFSET));
});
