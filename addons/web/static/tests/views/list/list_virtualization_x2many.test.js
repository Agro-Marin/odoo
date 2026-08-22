// @ts-check

import { expect, test } from "@odoo/hoot";
import { queryAll, queryFirst } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
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

const LINE_COUNT = 150;

function seedLines(/** @type {any} */ count) {
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

/**
 * @param {HTMLElement} el
 * @returns {HTMLElement}
 */
function scrollContainerOf(el) {
    const scrollable = new Set(["auto", "scroll", "overlay"]);
    for (let node = el; node; node = node.parentElement) {
        if (
            node.scrollHeight > node.clientHeight &&
            scrollable.has(getComputedStyle(node).overflowY)
        ) {
            return node;
        }
    }
    return el;
}

test.tags("desktop");
test("every x2many row above the virtualization threshold is reachable", async () => {
    seedLines(LINE_COUNT);
    await mountView({ resModel: "parent", type: "form", resId: 1, arch: ARCH });

    const renderer = queryFirst(".o_field_x2many .o_list_renderer");
    expect(renderer.scrollHeight).toBe(renderer.clientHeight);

    const firstNames = queryAll(".o_field_x2many .o_data_row .o_data_cell").map((td) =>
        td.textContent.trim(),
    );
    expect(firstNames.at(0)).toBe("line 1");

    const scroller = scrollContainerOf(renderer);
    expect(scroller).not.toBe(renderer);
    scroller.scrollTop = scroller.scrollHeight;
    await animationFrame();
    await animationFrame();

    const lastNames = queryAll(".o_field_x2many .o_data_row .o_data_cell").map((td) =>
        td.textContent.trim(),
    );
    expect(lastNames.at(-1)).toBe(`line ${LINE_COUNT}`);
});

test.tags("desktop");
test("x2many table never claims more height than its rows occupy", async () => {
    seedLines(LINE_COUNT);
    await mountView({ resModel: "parent", type: "form", resId: 1, arch: ARCH });

    const rows = queryAll(".o_field_x2many .o_data_row");
    const rowHeight = rows[0].getBoundingClientRect().height;
    const spacerHeight = queryAll(".o_field_x2many .o_virtual_spacer > td").reduce(
        (total, td) => total + td.getBoundingClientRect().height,
        0,
    );
    const renderedHeight = rows.reduce(
        (total, tr) => total + tr.getBoundingClientRect().height,
        0,
    );

    const claimed = spacerHeight + renderedHeight;
    const real = LINE_COUNT * rowHeight;
    expect(Math.abs(claimed - real)).toBeLessThan(rowHeight * 2, {
        message: `claimed ${claimed}px for ${LINE_COUNT} rows of ${rowHeight}px (expected ~${real}px)`,
    });
});
