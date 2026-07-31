// @ts-check

/**
 * @module tests/views/list/list_footer_alignment
 *
 * The ``<tfoot>`` totals row and the body address the SAME grid, so the footer
 * must be laid out from the columns the RENDERER produced — not from a second,
 * independently-derived column list.
 *
 * ``ListRenderer`` narrows its columns through two documented override seams
 * (``processAllColumns``, ``getActiveColumns``), used fork-wide by
 * product/sale (drop the description column), account (resolve
 * ``optional="conditional"``) and hr_payroll (remap ``payrun_optional``).
 * ``ListAggregatesRow`` used to re-derive the columns itself and so missed all
 * of them: with one extra column ahead of the first aggregate,
 * ``getGroupNameCellColSpan`` over-counted and every total was pushed out of
 * its own column — into a sub-pixel sliver past the last header.
 */

import { describe, expect, test } from "@odoo/hoot";
import { queryAll, queryAllTexts } from "@odoo/hoot-dom";
import {
    defineModels,
    fields,
    models,
    mountView,
    webModels,
} from "@web/../tests/web_test_helpers";
import { registry } from "@web/core/registry";

class Foo extends models.Model {
    name = fields.Char();
    product = fields.Char();
    qty = fields.Integer({ aggregator: "sum" });

    _records = [
        { id: 1, name: "a", product: "xphone", qty: 2 },
        { id: 2, name: "b", product: "xpad", qty: 3 },
    ];
}

const { ResCompany, ResPartner, ResUsers } = webModels;
defineModels([Foo, ResCompany, ResPartner, ResUsers]);

/** Grid width a row covers, honouring colspans. */
function rowWidth(cells) {
    return cells.reduce((n, td) => n + (Number(td.getAttribute("colspan")) || 1), 0);
}

/** Index of the header column whose horizontal span contains ``x``, or -1. */
function columnAt(x) {
    const ths = queryAll("thead th");
    for (let i = 0; i < ths.length; i++) {
        const rect = ths[i].getBoundingClientRect();
        if (x >= rect.left && x < rect.right) {
            return i;
        }
    }
    return -1;
}

const ARCH_BODY = `
    <field name="name"/>
    <field name="product"/>
    <field name="qty" sum="Total qty"/>`;

/**
 * Register a js_class whose renderer narrows the ACTIVE columns — the shape of
 * ``product/product_name_and_description.js`` (drops the description column)
 * and ``sale/sale_order_line_field.js`` (drops ``product_template_id``).
 */
function registerNarrowingRenderer(name, dropped) {
    const listView = registry.category("views").get("list");
    class NarrowingRenderer extends listView.Renderer {
        getActiveColumns() {
            return super
                .getActiveColumns()
                .filter((/** @type {any} */ column) => column.name !== dropped);
        }
    }
    registry.category("views").add(name, { ...listView, Renderer: NarrowingRenderer });
}

describe("footer follows the renderer's column set", () => {
    test.tags("desktop");
    test("plain list: footer covers exactly the body's columns", async () => {
        await mountView({
            resModel: "foo",
            type: "list",
            arch: `<list>${ARCH_BODY}</list>`,
        });
        const body = queryAll("tbody tr.o_data_row:first-child td");
        expect(rowWidth(queryAll("tfoot tr td"))).toBe(body.length);
    });

    test.tags("desktop");
    test("narrowing renderer: footer covers exactly the body's columns", async () => {
        registerNarrowingRenderer("narrowing_list", "product");
        await mountView({
            resModel: "foo",
            type: "list",
            arch: `<list js_class="narrowing_list">${ARCH_BODY}</list>`,
        });
        expect(queryAllTexts("thead th")).not.toInclude("PRODUCT");
        const body = queryAll("tbody tr.o_data_row:first-child td");
        expect(rowWidth(queryAll("tfoot tr td"))).toBe(body.length);
    });

    test.tags("desktop");
    test("narrowing renderer: the total still lands under its own column", async () => {
        registerNarrowingRenderer("narrowing_list_px", "product");
        await mountView({
            resModel: "foo",
            type: "list",
            arch: `<list js_class="narrowing_list_px">${ARCH_BODY}</list>`,
        });
        const headers = queryAllTexts("thead th");
        const qtyIndex = headers.findIndex((h) => h.trim().toUpperCase() === "QTY");
        const totalCell = queryAll("tfoot tr td").find(
            (td) => td.innerText.trim() === "5",
        );
        expect(totalCell).not.toBe(undefined);
        const rect = totalCell.getBoundingClientRect();
        expect(columnAt(rect.left + rect.width / 2)).toBe(qtyIndex);
    });

    test.tags("desktop");
    test("narrowing renderer without aggregates: footer width still matches", async () => {
        registerNarrowingRenderer("narrowing_list_noagg", "product");
        await mountView({
            resModel: "foo",
            type: "list",
            arch: `<list js_class="narrowing_list_noagg">
                    <field name="name"/>
                    <field name="product"/>
                    <field name="qty" optional="show"/>
                </list>`,
        });
        const body = queryAll("tbody tr.o_data_row:first-child td");
        expect(rowWidth(queryAll("tfoot tr td"))).toBe(body.length);
    });
});
