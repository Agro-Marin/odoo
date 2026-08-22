// @ts-check

import { expect, test } from "@odoo/hoot";
import { queryAll, queryFirst } from "@odoo/hoot-dom";
import {
    defineModels,
    fields,
    models,
    mountView,
    webModels,
} from "@web/../tests/web_test_helpers";

class Foo extends models.Model {
    name = fields.Char();
    _records = Array.from({ length: 400 }, (_, i) => ({
        id: i + 1,
        name: `record ${i + 1}`,
    }));
}

const { ResCompany, ResPartner, ResUsers } = webModels;

defineModels([Foo, ResCompany, ResPartner, ResUsers]);

const DEFAULT_ROW_HEIGHT = 41;

function forceRowHeight(/** @type {number} */ px) {
    const style = document.createElement("style");
    style.textContent = `.o_list_table > tbody > tr.o_data_row > td {
        padding-top: 0 !important;
        padding-bottom: 0 !important;
        height: ${px}px !important;
        line-height: ${px}px !important;
    }`;
    document.head.appendChild(style);
    return () => style.remove();
}

test.tags("desktop");
test("virtualization geometry matches the real row height on first render", async () => {
    const restore = forceRowHeight(20);
    try {
        await mountView({
            resModel: "foo",
            type: "list",
            arch: `<list limit="400"><field name="name"/></list>`,
        });

        const renderedRows = queryAll(".o_data_row");
        expect(renderedRows.length).toBeGreaterThan(0);
        expect(renderedRows.length).toBeLessThan(400);

        const actualRowHeight = renderedRows[0].getBoundingClientRect().height;
        expect(actualRowHeight).not.toBe(DEFAULT_ROW_HEIGHT);

        const spacerHeight = queryAll(".o_virtual_spacer > td").reduce(
            (total, td) => total + td.getBoundingClientRect().height,
            0,
        );
        const renderedHeight = renderedRows.reduce(
            (total, tr) => total + tr.getBoundingClientRect().height,
            0,
        );

        const claimedHeight = spacerHeight + renderedHeight;
        const expectedHeight = 400 * actualRowHeight;
        expect(Math.abs(claimedHeight - expectedHeight)).toBeLessThan(
            actualRowHeight * 2,
            {
                message: `claimed ${claimedHeight}px for 400 rows of ${actualRowHeight}px (expected ~${expectedHeight}px)`,
            },
        );
    } finally {
        restore();
    }
});

test.tags("desktop");
test("scrolling to the end of a virtualized list reaches the last record", async () => {
    const restore = forceRowHeight(20);
    try {
        await mountView({
            resModel: "foo",
            type: "list",
            arch: `<list limit="400"><field name="name"/></list>`,
        });

        const scrollable = queryFirst(".o_list_renderer");
        scrollable.scrollTop = scrollable.scrollHeight;
        scrollable.dispatchEvent(new Event("scroll"));
        await new Promise((resolve) => requestAnimationFrame(() => resolve()));
        await new Promise((resolve) => requestAnimationFrame(() => resolve()));

        const names = queryAll(".o_data_row .o_data_cell").map((td) => td.textContent);
        expect(names.at(-1)).toBe("record 400");
    } finally {
        restore();
    }
});
