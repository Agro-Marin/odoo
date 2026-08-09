// @ts-check

import { expect, test } from "@odoo/hoot";
import { animationFrame } from "@odoo/hoot-mock";
import { onWillRender } from "@odoo/owl";
import {
    contains,
    defineModels,
    fields,
    models,
    mountView,
    patchWithCleanup,
    webModels,
} from "@web/../tests/web_test_helpers";
import { ListRecordRow } from "@web/views/list/list_record_row";
import { ListRenderer } from "@web/views/list/list_renderer";

class Foo extends models.Model {
    foo = fields.Char();
    int_field = fields.Integer();

    _records = Array.from({ length: 20 }, (_, i) => ({
        id: i + 1,
        foo: `row ${i + 1}`,
        int_field: i,
    }));
}

defineModels([...Object.values(webModels), Foo]);

const ARCH = `
    <list editable="bottom">
        <field name="foo"/>
        <field name="int_field"/>
    </list>
`;

/**
 * Counts row re-renders, and records `rowFlags.canSelectRecord` once per
 * renderer render -- that flag is the one value every row subscribes to, so its
 * value SEQUENCE across an interaction is what decides how much of the list
 * repaints.
 */
function instrument() {
    const s = { rowRenders: 0, /** @type {boolean[]} */ flagPerRender: [] };
    patchWithCleanup(ListRenderer.prototype, {
        setup() {
            super.setup();
            onWillRender(() =>
                s.flagPerRender.push(
                    /** @type {any} */ (this).rowFlags.canSelectRecord,
                ),
            );
        },
    });
    patchWithCleanup(ListRecordRow.prototype, {
        setup() {
            super.setup();
            onWillRender(() => s.rowRenders++);
        },
    });
    return s;
}

test(`moving the edited row does not repaint every row`, async () => {
    const s = instrument();
    await mountView({ resModel: "foo", type: "list", arch: ARCH });
    await animationFrame();

    // Entering edition legitimately touches every row: each selector checkbox
    // becomes disabled. That cost is expected and is NOT what this pins.
    await contains(`tbody tr:eq(0) td[name=foo]`).click();
    await animationFrame();

    // Handing edition to another row changes only the two rows involved.
    // Before DynamicList#isEditing, `canSelectRecord` went false -> true ->
    // false across the handover and every row re-rendered twice (81 renders on
    // a 40-row list). A handful of renders is fine; a multiple of the row count
    // is the regression.
    s.rowRenders = 0;
    s.flagPerRender = [];
    await contains(`tbody tr:eq(2) td[name=foo]`).click();
    await animationFrame();

    expect(`tbody tr:eq(2)`).toHaveClass("o_selected_row");
    expect(s.rowRenders).toBeLessThan(10, {
        message: `moving edition re-rendered ${s.rowRenders} rows of 20`,
    });
    expect(s.flagPerRender.some((v) => v === true)).toBe(false, {
        message: "canSelectRecord must not flip back to true mid-handover",
    });
});

test(`selectors stay disabled for the whole handover`, async () => {
    await mountView({ resModel: "foo", type: "list", arch: ARCH });

    await contains(`tbody tr:eq(0) td[name=foo]`).click();
    await animationFrame();
    expect(`tbody tr:eq(5) .o_list_record_selector input`).toHaveProperty(
        "disabled",
        true,
        { message: "a row is in edition: other selectors are disabled" },
    );

    await contains(`tbody tr:eq(2) td[name=foo]`).click();
    await animationFrame();
    expect(`tbody tr:eq(2)`).toHaveClass("o_selected_row");
    expect(`tbody tr:eq(5) .o_list_record_selector input`).toHaveProperty(
        "disabled",
        true,
        { message: "edition moved, not ended: selectors are still disabled" },
    );
});

test(`leaving edition re-enables the selectors`, async () => {
    await mountView({ resModel: "foo", type: "list", arch: ARCH });

    await contains(`tbody tr:eq(0) td[name=foo]`).click();
    await animationFrame();
    expect(`tbody tr:eq(5) .o_list_record_selector input`).toHaveProperty(
        "disabled",
        true,
    );

    // Clicking outside the table leaves edition entirely: `isEditing` must go
    // false, so this is the guard against `_editHandover` stranding the list.
    await contains(`.o_content`).click();
    await animationFrame();
    expect(`tbody tr.o_selected_row`).toHaveCount(0);
    expect(`tbody tr:eq(5) .o_list_record_selector input`).toHaveProperty(
        "disabled",
        false,
        { message: "no row in edition: selectors are enabled again" },
    );
});
