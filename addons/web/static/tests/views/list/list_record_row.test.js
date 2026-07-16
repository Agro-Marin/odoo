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
 */

import { expect, test } from "@odoo/hoot";
import { queryAll, queryFirst } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { status, useState } from "@odoo/owl";
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
    /* xml */ `
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
    // The inherited row body is intact (C4): one name cell per row.
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

    // Assign a NEW instance field after every row installed its accessors,
    // then force a row re-render.
    captured.renderer.lateAssignedFlag = true;
    captured.renderer.rowState.highlight = true;
    await animationFrame();

    expect(warnings.filter((msg) => msg.includes("lateAssignedFlag"))).toHaveLength(1);
    expect(queryFirst(".o_data_row").dataset.highlight).toBe("on");
});

test.tags("desktop");
test("destroyed row: shadow subscriptions are inert and caches are cleared", async () => {
    // OWL only clears its own render callback's reactive subscriptions on
    // destroy — the row's custom ``_shadowRender`` callback (C3 subscriptions
    // to delegated renderer state) stays registered in the reactivity maps.
    // The WeakRef + status guard must make such a leaked subscription inert
    // (no re-render of a destroyed row), and ``onWillDestroy`` must clear the
    // delegation caches so the destroyed row stops referencing renderer state.
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

    // Fold the first group: its row component is destroyed.
    await contains(".o_group_header").click();
    await animationFrame();
    const destroyed = rowInstances.filter((row) => status(row) === "destroyed");
    expect(destroyed.length).toBeGreaterThan(0);

    let renders = 0;
    for (const row of destroyed) {
        row.render = () => renders++;
        // A leaked shadow subscription firing after destroy is a no-op: the
        // WeakRef in _shadowRender derefs to a destroyed component, so it never
        // calls render(). (The caches are intentionally left for normal GC —
        // eagerly clearing them mid-suite disturbs OWL's reactive-callback GC;
        // see the note in list_record_row.js.)
        row._shadowRender();
    }
    // Mutating the renderer state the rows subscribed to (C3) must not
    // re-render destroyed rows either…
    captured.renderer.rowState.highlight = true;
    await animationFrame();
    expect(renders).toBe(0);
    // …while live rows still react.
    expect(queryAll(".o_data_row").every((row) => row.dataset.highlight === "on")).toBe(
        true,
    );
});

test("row.group resolves the flat parentGroup even when virtualization is active", () => {
    // Regression: the virtualized branch used to short-circuit ``get group()``
    // to undefined, dropping group context for grouped lists past the
    // virtualization threshold (Enter mis-targets the new row,
    // onEditNextRecord opens the form view instead of the next inline row).
    // The flat grid carries ``parentGroup`` regardless of virtualization, so
    // the getter must return it unconditionally.
    const groupGetter = Object.getOwnPropertyDescriptor(
        ListRecordRow.prototype,
        "group",
    ).get;
    const parentGroup = { id: "group-7" };
    const makeThis = (virtIsActive) => ({
        props: {
            record: { id: 5 },
            group: undefined,
            renderer: {
                virt: { isActive: virtIsActive },
                gridState: {
                    findRowByRecordId: (id) =>
                        id === "5" ? { parentGroup } : undefined,
                },
            },
        },
    });
    // Non-virtualized (unchanged behavior) AND virtualized (the fix) both
    // resolve the enclosing group.
    expect(groupGetter.call(makeThis(false))).toBe(parentGroup);
    expect(groupGetter.call(makeThis(true))).toBe(parentGroup);
});
