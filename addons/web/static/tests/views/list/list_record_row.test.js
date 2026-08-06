// @ts-check

/**
 * @module tests/views/list/list_record_row
 *
 * Contract tests for the ``ListRecordRow`` renderer-delegation machinery
 * (see the compatibility contract documented in ``list_record_row.js``):
 *
 * - C1: bare-name expressions in (subclass) record row templates dispatch
 *   against the RENDERER, with ``record`` resolving to THIS row's record —
 *   including through default parameters (``method(record = this.record)``).
 * - C2: writes from row-template handlers (``this.x = …``) land on the
 *   renderer instance.
 * - C3: renderer reactive state read from a row template subscribes the row:
 *   mutating it re-renders the rows (without a full renderer render).
 * - C4: a subclass ``static recordRowTemplate`` (template inheriting
 *   ``web.ListRenderer.RecordRow``) is resolved and rendered by the row
 *   component; the inherited row body stays intact.
 * - C5: the derived row class exposes the renderer class's ``components``
 *   as a live view, not a snapshot.
 * - C6 (debug mode): a renderer instance field assigned after the delegation
 *   accessors were installed triggers a console warning instead of failing
 *   silently.
 * - C7: ``record``/``group``/``groupId`` are the row's own props — the
 *   explicit row context, not a grid lookup.
 * - C8: the row template's actual reads define the row's reactive
 *   subscriptions: one record's data change re-renders that row standalone.
 */

import { expect, test } from "@odoo/hoot";
import { queryAll, queryFirst } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { onRendered, status, useState } from "@odoo/owl";
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
            <attribute name="t-att-data-label">rowLabel()</attribute>
            <attribute name="t-att-data-highlight">rowState.highlight ? 'on' : 'off'</attribute>
            <attribute name="t-on-click">() => this.noteRow()</attribute>
        </xpath>
    </t>`,
);

/**
 * Register a ``custom_row_list`` js_class whose renderer uses the inheriting
 * row template above, and expose the mounted renderer instance.
 *
 * @returns {{ get renderer(): any }}
 */
function setupCustomRowList() {
    const captured = { renderer: null };
    const listView = registry.category("views").get("list");
    class CustomListRenderer extends listView.Renderer {
        static recordRowTemplate = "test_list_record_row.RecordRow";
        setup() {
            super.setup();
            this.rowState = useState({ highlight: false });
            captured.renderer = this;
        }
        rowLabel(record = this.record) {
            return `label:${record.data.name}`;
        }
        noteRow() {
            this.notedRecordId = this.record.id;
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
test("bare-name methods dispatch on the renderer with the row's record (C1/C4)", async () => {
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
test("writes from row template handlers land on the renderer (C2)", async () => {
    const captured = setupCustomRowList();
    await mountView({ resModel: "foo", type: "list", arch: CUSTOM_ROW_ARCH });

    const secondRow = queryAll(".o_data_row")[1];
    await contains(secondRow.querySelector(".o_data_cell")).click();
    expect(captured.renderer.notedRecordId).toBe(secondRow.dataset.id);
});

test.tags("desktop");
test("rows subscribe to renderer reactive state read in the row template (C3)", async () => {
    const captured = setupCustomRowList();
    await mountView({ resModel: "foo", type: "list", arch: CUSTOM_ROW_ARCH });

    const rows = queryAll(".o_data_row");
    expect(rows.map((row) => row.dataset.highlight)).toEqual(["off", "off", "off"]);

    captured.renderer.rowState.highlight = true;
    await animationFrame();
    expect(rows.map((row) => row.dataset.highlight)).toEqual(["on", "on", "on"]);
});

test("row component class components are a live view over the renderer's (C5)", () => {
    class TestRenderer extends ListRenderer {}
    TestRenderer.components = { ...ListRenderer.components };
    const RowClass = getRowComponentClass(TestRenderer);
    expect(RowClass.components).toBe(TestRenderer.components);

    class LateComponent {}
    TestRenderer.components = { ...TestRenderer.components, LateComponent };
    expect(RowClass.components.LateComponent).toBe(LateComponent);
});

test.tags("desktop");
test("late renderer field assignment warns in debug mode (C6)", async () => {
    patchWithCleanup(odoo, { debug: "1" });
    const warnings = [];
    patchWithCleanup(console, {
        warn: (message) => warnings.push(String(message)),
    });
    const captured = setupCustomRowList();
    await mountView({ resModel: "foo", type: "list", arch: CUSTOM_ROW_ARCH });

    expect(warnings).toEqual([]);

    captured.renderer.lateAssignedFlag = true;
    captured.renderer.rowState.highlight = true;
    await animationFrame();

    expect(warnings.filter((msg) => msg.includes("lateAssignedFlag"))).toHaveLength(1);
    expect(queryFirst(".o_data_row").dataset.highlight).toBe("on");
});

test.tags("desktop");
test("destroyed row: shadow subscriptions are inert and caches are cleared", async () => {
    /** @type {any[]} */
    const rowInstances = [];
    patchWithCleanup(ListRecordRow.prototype, {
        setup() {
            super.setup();
            rowInstances.push(this);
        },
    });
    const captured = setupCustomRowList();
    await mountView({
        resModel: "foo",
        type: "list",
        arch: `<list js_class="custom_row_list" expand="1"><field name="name"/></list>`,
        groupBy: ["name"],
    });
    expect(queryAll(".o_data_row")).toHaveLength(3);
    expect(rowInstances).toHaveLength(3);

    await contains(".o_group_header").click();
    await animationFrame();
    const destroyed = rowInstances.filter((row) => status(row) === "destroyed");
    expect(destroyed.length).toBeGreaterThan(0);

    let renders = 0;
    for (const row of destroyed) {
        row.render = () => renders++;
        row._shadowRender();
    }
    captured.renderer.rowState.highlight = true;
    await animationFrame();
    expect(renders).toBe(0);
    expect(queryAll(".o_data_row").every((row) => row.dataset.highlight === "on")).toBe(
        true,
    );
});

test("record, group and groupId come from the row's own props (C7)", () => {
    // The row context is explicit: `record`/`group`/`groupId` are the row's
    // own props — `props.record` is the reactive OWL re-targets to the row,
    // so template reads through these getters subscribe THIS row.
    const get = (name) =>
        Object.getOwnPropertyDescriptor(ListRecordRow.prototype, name).get;
    const record = { id: 5 };
    const group = { id: "group-7" };
    const row = { props: { record, group, groupId: "group-7" } };
    expect(get("record").call(row)).toBe(record);
    expect(get("group").call(row)).toBe(group);
    expect(get("groupId").call(row)).toBe("group-7");
});

test.tags("desktop");
test("a record data change re-renders that row standalone (C8)", async () => {
    // The template's actual reads define the row's reactive subscriptions:
    // mutating one record's data re-renders that row — and only that row —
    // without a full renderer render.
    const rowRenders = [];
    patchWithCleanup(ListRecordRow.prototype, {
        setup() {
            super.setup();
            onRendered(() => rowRenders.push(this.props.record.resId));
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
