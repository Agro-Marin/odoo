// @ts-check

import { expect, test } from "@odoo/hoot";
import { queryAll } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { onRendered, useState } from "@odoo/owl";
import {
    contains,
    defineModels,
    fields,
    models,
    mountView,
    patchWithCleanup,
    webModels,
} from "@web/../tests/web_test_helpers";
import { registry } from "@web/core/registry";
import { registerTemplate } from "@web/core/templates";
import { getRowComponentClass, ListRecordRow } from "@web/views/list/list_record_row";
import { ListRenderer } from "@web/views/list/list_renderer";

class Foo extends models.Model {
    name = fields.Char();
    _records = [
        { id: 1, name: "alpha" },
        { id: 2, name: "beta" },
        { id: 3, name: "gamma" },
    ];
}

const { ResCompany, ResPartner, ResUsers } = webModels;

defineModels([Foo, ResCompany, ResPartner, ResUsers]);

registerTemplate(
    "test_list_record_row.RecordRow",
    "/web/static/tests/views/list/list_record_row.test.js",
    `
    <t t-name="test_list_record_row.RecordRow"
       t-inherit="web.ListRenderer.RecordRow"
       t-inherit-mode="primary">
        <xpath expr="//tr" position="attributes">
            <attribute name="t-att-data-label">api.rowLabel(record)</attribute>
            <attribute name="t-att-data-highlight">props.rowState.highlight ? 'on' : 'off'</attribute>
            <attribute name="t-on-click">() => api.noteRow(record)</attribute>
        </xpath>
    </t>`,
);

/**
 * @returns {{ get renderer(): any, rendererRenders: number }}
 */
function setupCustomRowList() {
    /** @type {{ renderer: any, rendererRenders: number }} */
    const captured = { renderer: null, rendererRenders: 0 };
    const listView = registry.category("views").get("list");
    class CustomListRenderer extends listView.Renderer {
        static recordRowTemplate = "test_list_record_row.RecordRow";
        setup() {
            super.setup();
            this.rowState = useState({ highlight: false });
            captured.renderer = this;
            onRendered(() => captured.rendererRenders++);
        }
        /** @param {any} record */
        rowLabel(record) {
            return `label:${record.data.name}`;
        }

        /** @param {any} record */
        noteRow(record) {
            this.notedRecord = record;
        }
        buildRowApi() {
            return {
                ...super.buildRowApi(),
                rowLabel: (/** @type {any} */ record) => this.rowLabel(record),
                noteRow: (/** @type {any} */ record) =>
                    this.noteRow(this.resolveRowRecord(record)),
            };
        }

        /**
         * @param {any} record
         * @param {any} group
         * @param {any} groupId
         */
        getRowProps(record, group, groupId) {
            return {
                ...super.getRowProps(record, group, groupId),
                rowState: this.rowState,
            };
        }
    }
    registry
        .category("views")
        .add(
            "custom_row_list",
            { ...listView, Renderer: CustomListRenderer },
            { force: true },
        );
    return captured;
}

const CUSTOM_ROW_ARCH = `<list js_class="custom_row_list"><field name="name"/></list>`;

test.tags("desktop");
test("api members dispatch on the renderer with the row's record (C1/C4)", async () => {
    setupCustomRowList();
    await mountView({ resModel: "foo", type: "list", arch: CUSTOM_ROW_ARCH });

    const rows = queryAll(".o_data_row");
    expect(rows.map((row) => row.dataset.label)).toEqual([
        "label:alpha",
        "label:beta",
        "label:gamma",
    ]);
    expect(".o_data_row .o_data_cell[name='name']").toHaveCount(3);
});

test.tags("desktop");
test("action callbacks resolve the record to the renderer's context (C2)", async () => {
    const captured = setupCustomRowList();
    await mountView({ resModel: "foo", type: "list", arch: CUSTOM_ROW_ARCH });

    const secondRow = queryAll(".o_data_row")[1];
    await contains(secondRow.querySelector(".o_data_cell")).click();
    expect(captured.renderer.notedRecord.id).toBe(secondRow.dataset.id);
    expect(captured.renderer.notedRecord).toBe(captured.renderer.props.list.records[1]);
});

test.tags("desktop");
test("getRowProps state re-renders rows without a renderer render (C3)", async () => {
    const captured = setupCustomRowList();
    await mountView({ resModel: "foo", type: "list", arch: CUSTOM_ROW_ARCH });

    const rows = queryAll(".o_data_row");
    expect(rows.map((row) => row.dataset.highlight)).toEqual(["off", "off", "off"]);
    const rendererRendersBefore = captured.rendererRenders;

    captured.renderer.rowState.highlight = true;
    await animationFrame();
    expect(rows.map((row) => row.dataset.highlight)).toEqual(["on", "on", "on"]);
    expect(captured.rendererRenders).toBe(rendererRendersBefore);
});

test("row component class components are a live view over the renderer's (C5)", () => {
    const TestRenderer = /** @type {any} */ (class extends ListRenderer {});
    TestRenderer.components = { ...ListRenderer.components };
    const RowClass = /** @type {any} */ (getRowComponentClass(TestRenderer));
    expect(RowClass.components).toBe(TestRenderer.components);

    class LateComponent {}
    TestRenderer.components = { ...TestRenderer.components, LateComponent };
    expect(RowClass.components.LateComponent).toBe(LateComponent);
});

test("record, group and groupId come from the row's own props (C7)", () => {
    const get = (/** @type {string} */ name) =>
        /** @type {any} */ (
            Object.getOwnPropertyDescriptor(ListRecordRow.prototype, name)
        ).get;
    const record = { id: 5 };
    const group = { id: "group-7" };
    const row = { props: { record, group, groupId: "group-7" } };
    expect(get("record").call(row)).toBe(record);
    expect(get("group").call(row)).toBe(group);
    expect(get("groupId").call(row)).toBe("group-7");
});

test.tags("desktop");
test("a record data change re-renders that row standalone (C8)", async () => {
    /** @type {any[]} */
    const rowRenders = [];
    patchWithCleanup(ListRecordRow.prototype, {
        setup() {
            super.setup();
            onRendered(() =>
                rowRenders.push(/** @type {any} */ (this).props.record.resId),
            );
        },
    });
    const captured = setupCustomRowList();
    await mountView({ resModel: "foo", type: "list", arch: CUSTOM_ROW_ARCH });
    rowRenders.length = 0;

    const record = captured.renderer.props.list.records[1];
    await record.update({ name: "beta-prime" });
    await animationFrame();

    expect(rowRenders).toEqual([2]);
    expect(queryAll(".o_data_row .o_data_cell").map((el) => el.textContent)).toEqual([
        "alpha",
        "beta-prime",
        "gamma",
    ]);
});
