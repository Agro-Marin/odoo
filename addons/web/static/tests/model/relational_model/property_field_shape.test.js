// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import {
    contains,
    defineModels,
    fields,
    models,
    mountView,
    onRpc,
    webModels,
} from "@web/../tests/web_test_helpers";
import { describePropertyDefinitionAsField } from "@web/model/property_fields";
import { getPropertyFieldColumns } from "@web/views/list/list_column_utils";

/**
 * A property reaches the views as a synthetic field named
 * `<properties field>.<property name>`, and `list_column_utils` decides which
 * property columns belong to which `properties` column by comparing
 * `field.relatedPropertyField.name` against the column's name.
 *
 * Three places used to build that synthetic field and they disagreed on the
 * key: the group-by loader wrote `{ fieldName }` where every consumer and
 * `model/types.js` read `.name`. The visible consequence was that grouping a
 * list *by* a property dropped every property column from that list -- the
 * optional-columns menu lost its only entry and the toggle disappeared with it.
 *
 * The three producers are now one function, and these tests pin both halves:
 * the shape it emits, and the list behaviour that depends on it.
 */

const { ResCompany, ResPartner, ResUsers } = webModels;

const DEFINITION = { type: "char", name: "property_char", string: "Property char" };

class Bar extends models.Model {
    _name = "bar";
    name = fields.Char();
    definitions = fields.PropertiesDefinition();
    _records = [{ id: 1, name: "B1", definitions: [DEFINITION] }];
}

class Foo extends models.Model {
    _name = "foo";
    foo = fields.Char();
    m2o = fields.Many2one({ relation: "bar" });
    properties = fields.Properties({
        definition_record: "m2o",
        definition_record_field: "definitions",
    });
    _records = [
        { id: 1, foo: "yop", m2o: 1, properties: { property_char: "AAA" } },
        { id: 2, foo: "blip", m2o: 1, properties: { property_char: "BBB" } },
    ];
}

defineModels([Foo, Bar, ResCompany, ResPartner, ResUsers]);

const ARCH = `<list><field name="m2o"/><field name="properties"/></list>`;
const ROWS = [
    {
        id: 1,
        m2o: { id: 1, display_name: "B1" },
        properties: [{ ...DEFINITION, value: "AAA" }],
    },
];

describe("describePropertyDefinitionAsField", () => {
    describe.current.tags("headless");

    test("names the parent field under `name`, which is what consumers read", () => {
        const field = describePropertyDefinitionAsField(
            "properties.property_char",
            DEFINITION,
        );
        expect(field.name).toBe("properties.property_char");
        expect(field.propertyName).toBe("property_char");
        expect(field.relatedPropertyField).toEqual({ name: "properties" });
    });

    test("a definition that could not be read degrades to a char field", () => {
        const field = describePropertyDefinitionAsField("properties.gone", undefined);
        expect(field.type).toBe("char");
        expect(field.relatedPropertyField).toEqual({ name: "properties" });
    });

    test("the emitted shape is the one getPropertyFieldColumns filters on", () => {
        const relatedPropertyField = describePropertyDefinitionAsField(
            "properties.property_char",
            DEFINITION,
        ).relatedPropertyField;
        const list = {
            fields: {
                properties: { name: "properties", type: "properties" },
                "properties.property_char": {
                    name: "properties.property_char",
                    type: "char",
                    string: "Property char",
                    relatedPropertyField,
                },
            },
            activeFields: {
                properties: {},
                "properties.property_char": { relatedPropertyField },
            },
        };
        const columns = getPropertyFieldColumns(
            { id: "c1", name: "properties", type: "field" },
            /** @type {any} */ (list),
        );
        expect(columns).toHaveLength(1);
        expect(columns[0].name).toBe("properties.property_char");
    });
});

describe("a list grouped by a property", () => {
    describe.current.tags("desktop");

    test("still offers its property columns", async () => {
        onRpc("get_property_definition", () => ({ ...DEFINITION }));
        onRpc("web_read_group", () => ({
            length: 1,
            groups: [
                {
                    "properties.property_char": "AAA",
                    __extra_domain: [],
                    __count: 1,
                    __records: ROWS,
                },
            ],
        }));

        await mountView({
            resModel: "foo",
            type: "list",
            arch: ARCH,
            groupBy: ["properties.property_char"],
        });

        expect(`.o_data_row`).toHaveCount(1);
        await contains(`.o_optional_columns_dropdown_toggle`).click();
        expect(`.o-dropdown--menu input[type='checkbox']`).toHaveCount(1);
        await contains(`.o-dropdown--menu input[type='checkbox']`).click();
        expect(`.o_list_renderer th[data-name='properties.property_char']`).toHaveCount(
            1,
        );
    });

    test("CONTROL: grouped by a plain field, the columns are offered too", async () => {
        onRpc("web_read_group", () => ({
            length: 1,
            groups: [
                { m2o: [1, "B1"], __extra_domain: [], __count: 1, __records: ROWS },
            ],
        }));

        await mountView({
            resModel: "foo",
            type: "list",
            arch: ARCH,
            groupBy: ["m2o"],
        });

        expect(`.o_data_row`).toHaveCount(1);
        expect(`.o_optional_columns_dropdown_toggle`).toHaveCount(1);
    });
});
