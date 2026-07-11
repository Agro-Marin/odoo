// @ts-check

/**
 * @module tests/views/list/list_column_utils
 *
 * Regression guards for the property-column expansion memoization.
 *
 * `getPropertyFieldColumns` used to build fresh column objects on every call
 * while `processAllColumns` runs on every renderer render: any displayed
 * property column broke the elementwise identity check of
 * `ListRenderer._toStableColumns`, so the `columns` prop changed identity on
 * every render and every `ListRecordRow` re-rendered (defeating the row
 * render-isolation architecture), and the per-column format-option
 * memoization in `view_utils.js` missed every render.
 */

import { expect, test } from "@odoo/hoot";
import { animationFrame } from "@odoo/hoot-mock";
import { onRendered } from "@odoo/owl";
import {
    contains,
    defineModels,
    fields,
    models,
    mountView,
    patchWithCleanup,
    webModels,
} from "@web/../tests/web_test_helpers";
import { getPropertyFieldColumns } from "@web/views/list/list_column_utils";
import { ListRenderer } from "@web/views/list/list_renderer";

class Bar extends models.Model {
    name = fields.Char();
    definitions = fields.PropertiesDefinition();
    _records = [
        {
            id: 1,
            name: "bar 1",
            definitions: [
                { type: "char", name: "property_char", string: "Property char" },
            ],
        },
    ];
}

class Foo extends models.Model {
    name = fields.Char();
    m2o = fields.Many2one({ relation: "bar" });
    properties = fields.Properties({
        definition_record: "m2o",
        definition_record_field: "definitions",
    });
    _records = [
        { id: 1, name: "a", m2o: 1, properties: { property_char: "AAA" } },
        { id: 2, name: "b", m2o: 1, properties: { property_char: "BBB" } },
    ];
}

const { ResCompany, ResPartner, ResUsers } = webModels;

defineModels([Bar, Foo, ResCompany, ResPartner, ResUsers]);

test.tags("desktop");
test("columns identity is stable across renders with a displayed property column", async () => {
    /** @type {any[][]} */
    const capturedColumns = [];
    patchWithCleanup(ListRenderer.prototype, {
        setup() {
            super.setup(...arguments);
            onRendered(() => {
                capturedColumns.push(/** @type {any} */ (this).columns);
            });
        },
    });

    await mountView({
        resModel: "foo",
        type: "list",
        arch: `
            <list>
                <field name="m2o"/>
                <field name="properties"/>
            </list>`,
    });

    // Display the (optional-hidden by default) property column.
    await contains(".o_optional_columns_dropdown_toggle").click();
    await contains(".o-dropdown--menu input[type='checkbox']").click();
    expect(".o_list_renderer th[data-name='properties.property_char']").toHaveCount(1);

    // Trigger a full renderer render without a model reload (selection
    // toggle: the renderer subscribes to `selectAll` in its header).
    capturedColumns.length = 0;
    await contains(".o_data_row:eq(0) .o_list_record_selector input").click();
    await animationFrame();

    expect(capturedColumns.length).toBeGreaterThan(0);
    const previous = capturedColumns.at(-1);
    expect(previous.some((col) => col.name === "properties.property_char")).toBe(true);

    // Re-render again: same column set → the very same array (and thus the
    // same property column objects) must be reused.
    capturedColumns.length = 0;
    await contains(".o_data_row:eq(0) .o_list_record_selector input").click();
    await animationFrame();
    expect(capturedColumns.length).toBeGreaterThan(0);
    expect(capturedColumns.at(-1)).toBe(previous);
});

test("getPropertyFieldColumns is memoized per parent column and invalidated on definition change", () => {
    const column = {
        id: "column_1",
        name: "properties",
        type: "field",
        classNames: "",
        column_invisible: undefined,
    };
    const relatedPropertyField = { name: "properties", id: "properties" };
    const makePropField = () => ({
        name: "properties.property_char",
        type: "char",
        string: "Property char",
        relatedPropertyField,
    });
    const propField = makePropField();
    const list = {
        fields: {
            properties: { name: "properties", type: "properties" },
            "properties.property_char": propField,
        },
        activeFields: {
            properties: {},
            "properties.property_char": { relatedPropertyField },
        },
    };

    const first = getPropertyFieldColumns(column, list);
    expect(first).toHaveLength(1);
    // Same inputs → same array and same column objects.
    expect(getPropertyFieldColumns(column, list)).toBe(first);

    // New field definition object (property definitions changed) → rebuilt.
    list.fields["properties.property_char"] = makePropField();
    const rebuilt = getPropertyFieldColumns(column, list);
    expect(rebuilt).not.toBe(first);
    // And the rebuilt expansion is memoized in turn.
    expect(getPropertyFieldColumns(column, list)).toBe(rebuilt);
});
