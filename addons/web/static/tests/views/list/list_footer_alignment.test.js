// @ts-check

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

function rowWidth(cells) {
    return cells.reduce((n, td) => n + (Number(td.getAttribute("colspan")) || 1), 0);
}

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
