// @ts-check

import { expect, test } from "@odoo/hoot";
import { press } from "@odoo/hoot-dom";
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

function instrument() {
    const s = {
        rowRenders: 0,
        /** @type {boolean[]} */ flagPerRender: [],
        /** @type {boolean[]} */ isEditingPerRender: [],
    };
    patchWithCleanup(ListRenderer.prototype, {
        setup() {
            super.setup();
            onWillRender(() => {
                const flags = /** @type {any} */ (this).rowFlags;
                s.flagPerRender.push(flags.canSelectRecord);
                s.isEditingPerRender.push(flags.isEditing);
            });
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

    await contains(`tbody tr:eq(0) td[name=foo]`).click();
    await animationFrame();

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

test(`a button column does not repaint every row on handover`, async () => {
    const s = instrument();
    await mountView({
        resModel: "foo",
        type: "list",
        arch: `
            <list editable="bottom">
                <field name="foo"/>
                <field name="int_field"/>
                <button name="act" type="object" icon="fa-check"/>
            </list>
        `,
    });
    await animationFrame();

    await contains(`tbody tr:eq(0) td[name=foo]`).click();
    await animationFrame();

    s.rowRenders = 0;
    s.isEditingPerRender = [];
    await contains(`tbody tr:eq(2) td[name=foo]`).click();
    await animationFrame();

    expect(`tbody tr:eq(2)`).toHaveClass("o_selected_row");
    expect(s.rowRenders).toBeLessThan(10, {
        message: `moving edition re-rendered ${s.rowRenders} rows of 20`,
    });
    expect(s.isEditingPerRender.some((v) => v === false)).toBe(false, {
        message: "isEditing must not drop to false mid-handover",
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

    await contains(`.o_content`).click();
    await animationFrame();
    expect(`tbody tr.o_selected_row`).toHaveCount(0);
    expect(`tbody tr:eq(5) .o_list_record_selector input`).toHaveProperty(
        "disabled",
        false,
        { message: "no row in edition: selectors are enabled again" },
    );
});

test(`keyboard handover costs the same as the mouse`, async () => {
    const s = instrument();
    await mountView({ resModel: "foo", type: "list", arch: ARCH });
    await animationFrame();

    await contains(`tbody tr:eq(0) td[name=foo]`).click();
    await animationFrame();

    s.rowRenders = 0;
    s.isEditingPerRender = [];
    await press("Tab");
    await animationFrame();
    await press("Tab");
    await animationFrame();

    expect(`tbody tr:eq(1)`).toHaveClass("o_selected_row");
    expect(s.rowRenders).toBeLessThan(10, {
        message: `Tab to the next row repainted ${s.rowRenders} rows of 20`,
    });

    s.rowRenders = 0;
    s.isEditingPerRender = [];
    await press("Enter");
    await animationFrame();

    expect(`tbody tr:eq(2)`).toHaveClass("o_selected_row");
    expect(s.rowRenders).toBeLessThan(10, {
        message: `Enter to the next row repainted ${s.rowRenders} rows of 20`,
    });
    expect(s.isEditingPerRender.some((v) => v === false)).toBe(false, {
        message: "isEditing must span the two-step leave-then-enter",
    });
});

test(`a refused handover releases the slot instead of wedging isEditing`, async () => {
    /** @type {any} */
    let list;
    patchWithCleanup(ListRenderer.prototype, {
        setup() {
            super.setup();
            list = /** @type {any} */ (this).props.list;
        },
    });
    await mountView({ type: "list", resModel: "foo", arch: ARCH });

    const [first, second] = list.records;
    patchWithCleanup(list, { leaveEditMode: async () => false });

    expect(await list.enterEditMode(first)).toBe(false, {
        message: "the move was refused",
    });
    expect(list._editHandover.record).toBe(null, {
        message: "the handover slot is released on the refused branch too",
    });
    expect(list.isEditing).toBe(false, {
        message: "so isEditing does not wedge true with nothing in edition",
    });
    expect(await list.enterEditMode(second)).toBe(false);
    expect(list.isEditing).toBe(false);
});

test(`beginEditHandover releases even when the caller throws`, async () => {
    /** @type {any} */
    let listModel;
    patchWithCleanup(ListRenderer.prototype, {
        setup() {
            super.setup();
            listModel = /** @type {any} */ (this).props.list;
        },
    });
    await mountView({ type: "list", resModel: "foo", arch: ARCH });

    const record = listModel.records[0];
    expect(listModel.isEditing).toBe(false);
    const release = listModel.beginEditHandover(record);
    expect(listModel.isEditing).toBe(true, {
        message: "the slot spans the gap before any record is in edition",
    });
    release();
    expect(listModel.isEditing).toBe(false, {
        message: "and releasing it puts the flag back",
    });
});
