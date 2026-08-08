// @ts-check

/**
 * @module tests/views/list/list_virtualization_x2many
 *
 * `useVirtualGrid` derives the viewport span from
 * `scrollableRef.el.clientHeight`. For a standalone list that is correct —
 * `.o_list_renderer` is `overflow-y: auto` inside a height-constrained
 * `.o_content`, so `clientHeight` is a real viewport. Inside an x2many field
 * the same element grows to fit its content (the *form* is the scroller), so
 * `clientHeight` measures what was just rendered rather than what is visible.
 *
 * That makes the span self-referential, and the rows a user can actually reach
 * depend on which render happened to win. These tests pin the only property
 * that matters either way: every row of the x2many must be reachable, and the
 * table must never claim more height than its rows occupy.
 */

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
 * Resolve the element that actually scrolls the x2many, the same way
 * ``useListVirtualization`` does.
 *
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
    // The x2many list is not its own scroll viewport: the form scrolls it.
    expect(renderer.scrollHeight).toBe(renderer.clientHeight);

    const firstNames = queryAll(".o_field_x2many .o_data_row .o_data_cell").map((td) =>
        td.textContent.trim(),
    );
    expect(firstNames.at(0)).toBe("line 1");

    // Reachability is what matters, and under virtualization it is a property
    // of SCROLLING, not of the initial DOM: asserting the last row is present
    // up-front only held while virtualization was inert inside an x2many
    // (the renderer was mistaken for its own viewport, so the computed span
    // covered every row and nothing was ever windowed out).
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
