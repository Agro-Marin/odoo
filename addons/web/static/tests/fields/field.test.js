// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { Component, xml } from "@odoo/owl";
import { defineModels, fields, models } from "@web/../tests/web_test_helpers";
import { registry } from "@web/core/registry";
import {
    fieldVisualFeedback,
    getFieldFromRegistry,
    getPropertyFieldInfo,
    resetWidgetMissWarnings,
} from "@web/fields/field";
import { parseFieldNode } from "@web/views/field_arch";

class Partner extends models.Model {
    _name = "res.partner";
    _inherit = [];
    name = fields.Char();
    _records = [{ id: 1, name: "a" }];
}
defineModels([Partner]);

/** @param {Partial<any>} [overrides] */
function fakeRecord(overrides = {}) {
    return {
        isNew: false,
        isInEdition: false,
        data: { f: "value" },
        evalContextWithVirtualIds: {},
        isFieldInvalid: () => false,
        ...overrides,
    };
}

describe("fieldVisualFeedback", () => {
    test("falls back to the record value when no isEmpty hook is declared", () => {
        expect(fieldVisualFeedback({}, fakeRecord(), "f", {}).empty).toBe(false);
        expect(
            fieldVisualFeedback({}, fakeRecord({ data: { f: false } }), "f", {}).empty,
        ).toBe(true);
    });

    test("a declared isEmpty hook wins over the record value", () => {
        const field = { isEmpty: () => true };
        expect(fieldVisualFeedback(field, fakeRecord(), "f", {}).empty).toBe(true);
    });

    test("a new record is never empty", () => {
        const record = fakeRecord({ isNew: true, data: { f: false } });
        expect(fieldVisualFeedback({}, record, "f", {}).empty).toBe(false);
    });

    test("an explicitly-undefined isEmpty falls back instead of throwing", () => {
        expect(
            fieldVisualFeedback({ isEmpty: undefined }, fakeRecord(), "f", {}).empty,
        ).toBe(false);
        expect(
            fieldVisualFeedback(
                { isEmpty: undefined },
                fakeRecord({ data: { f: false } }),
                "f",
                {},
            ).empty,
        ).toBe(true);
    });

    test("an explicitly-undefined isValid falls back to the record", () => {
        expect(
            fieldVisualFeedback({ isValid: undefined }, fakeRecord(), "f", {}).invalid,
        ).toBe(false);
    });

    test("the registry accepts an entry carrying isEmpty: undefined", () => {
        class Probe extends Component {
            static template = xml``;
            static props = ["*"];
        }
        const reg = registry.category("fields");
        expect(() =>
            reg.add("test_field_undefined_hooks", {
                component: Probe,
                isEmpty: undefined,
                isValid: undefined,
            }),
        ).not.toThrow();
        expect(
            fieldVisualFeedback(
                reg.get("test_field_undefined_hooks"),
                fakeRecord(),
                "f",
                {},
            ).empty,
        ).toBe(false);
    });

    test("readonly and required come from their fieldInfo expressions", () => {
        const record = fakeRecord({ evalContextWithVirtualIds: { flag: true } });
        const on = fieldVisualFeedback({}, record, "f", {
            readonly: "flag",
            required: "True",
        });
        expect(on.readonly).toBe(true);
        expect(on.required).toBe(true);
        const off = fieldVisualFeedback({}, record, "f", {});
        expect(off.readonly).toBe(false);
        expect(off.required).toBe(false);
    });

    test("required is exposed as a getter, so it costs nothing unread", () => {
        const feedback = fieldVisualFeedback({}, fakeRecord(), "f", {});
        const descriptor = Object.getOwnPropertyDescriptor(feedback, "required");
        expect(typeof descriptor?.get).toBe("function");
    });
});

describe("getFieldFromRegistry", () => {
    test("resolves by widget, then by view prefix, then by bare type", () => {
        expect(getFieldFromRegistry("char", "char").component.name).toBe("CharField");
        expect(getFieldFromRegistry("char").component.name).toBe("CharField");
        expect(getFieldFromRegistry("text", "text", "list").component.name).toBe(
            "ListTextField",
        );
        expect(getFieldFromRegistry("text", "text").component.name).toBe("TextField");
    });

    test("an unknown widget falls back to the type's default component", () => {
        resetWidgetMissWarnings();
        expect(getFieldFromRegistry("char", "no_such_widget").component.name).toBe(
            "CharField",
        );
    });

    test("an unknown widget on an unknown type yields DefaultField", () => {
        resetWidgetMissWarnings();
        expect(
            getFieldFromRegistry("no_such_type", "no_such_widget").component.name,
        ).toBe("DefaultField");
    });
});

describe("getPropertyFieldInfo", () => {
    test("carries the viewType it is given", () => {
        expect(getPropertyFieldInfo({ name: "p", type: "char" }, "list").viewType).toBe(
            "list",
        );
        expect(
            getPropertyFieldInfo({ name: "p", type: "char" }, "kanban").viewType,
        ).toBe("kanban");
    });

    test("resolves the view-prefixed registry entry, not just the bare one", () => {
        const componentFor = (propertyField, viewType) =>
            getPropertyFieldInfo(propertyField, viewType).field.component.name;

        expect(componentFor({ name: "p", type: "text" }, "list")).toBe("ListTextField");
        expect(componentFor({ name: "p", type: "text" }, "form")).toBe("TextField");

        expect(componentFor({ name: "p", type: "datetime" }, "list")).toBe(
            "ListDateTimeField",
        );
        expect(componentFor({ name: "p", type: "datetime" }, "form")).toBe(
            "DateTimeField",
        );

        expect(
            componentFor(
                { name: "p", type: "many2many", relation: "res.users" },
                "list",
            ),
        ).toBe("ListMany2ManyTagsAvatarField");
        expect(
            componentFor(
                { name: "p", type: "many2many", relation: "res.users" },
                "kanban",
            ),
        ).toBe("KanbanMany2ManyTagsAvatarField");

        expect(componentFor({ name: "p", type: "text" }, undefined)).toBe("TextField");
    });

    test("relational properties on res.users/res.partner get the avatar widgets", () => {
        expect(
            getPropertyFieldInfo({ name: "p", type: "many2one", relation: "res.users" })
                .widget,
        ).toBe("many2one_avatar");
        expect(
            getPropertyFieldInfo({
                name: "p",
                type: "many2many",
                relation: "res.partner",
            }).widget,
        ).toBe("many2many_tags_avatar");
        expect(
            getPropertyFieldInfo({ name: "p", type: "many2many", relation: "other" })
                .widget,
        ).toBe("many2many_tags");
    });

    test("agrees on shape with parseFieldNode, the other producer", () => {
        const node = new DOMParser().parseFromString(
            `<field name="name"/>`,
            "text/xml",
        ).documentElement;
        const arch = parseFieldNode(
            node,
            { "res.partner": { fields: { name: { type: "char", string: "N" } } } },
            "res.partner",
            "list",
            null,
        );
        const property = getPropertyFieldInfo(
            { name: "name", type: "char", string: "N" },
            "list",
        );
        const onlyArch = Object.keys(arch)
            .filter((k) => !(k in property))
            .sort();
        const onlyProperty = Object.keys(property)
            .filter((k) => !(k in arch) && k !== "relatedPropertyField")
            .sort();
        expect({ onlyArch, onlyProperty }).toEqual({ onlyArch: [], onlyProperty: [] });
    });
});
