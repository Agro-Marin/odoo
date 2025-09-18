// @ts-check

/**
 * Pure unit tests for record_validator.js.
 *
 * Tests the required-field validation logic without OWL, DOM, or a mock server.
 * All callbacks (isInvisible, isRequired, isChildListValid) are plain functions.
 */

import { describe, expect, test } from "@odoo/hoot";
import { findUnsetRequiredFields } from "@web/model/relational_model/record_validator";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeCallbacks({ invisible = [], required = [], invalidLists = [] } = {}) {
    return {
        isInvisible: (name) => invisible.includes(name),
        isRequired: (name) => required.includes(name),
        isChildListValid: (name, list) => !invalidLists.includes(name),
    };
}

// ---------------------------------------------------------------------------
// findUnsetRequiredFields — basic scalar types
// ---------------------------------------------------------------------------

describe("findUnsetRequiredFields — scalar types", () => {
    const fields = {
        name: { type: "char" },
        description: { type: "text" },
        amount: { type: "float" },
        qty: { type: "integer" },
        price: { type: "monetary" },
        active: { type: "boolean" },
    };

    test("returns empty set when no fields are required", () => {
        const activeFields = { name: {}, description: {}, amount: {} };
        const data = { name: false, description: false, amount: 0 };
        const result = findUnsetRequiredFields(activeFields, fields, data, makeCallbacks());
        expect(result.size).toBe(0);
    });

    test("flags required char field when value is false", () => {
        const activeFields = { name: {} };
        const data = { name: false };
        const result = findUnsetRequiredFields(activeFields, fields, data, makeCallbacks({ required: ["name"] }));
        expect(result.has("name")).toBe(true);
    });

    test("does not flag required char field when value is set", () => {
        const activeFields = { name: {} };
        const data = { name: "Partner" };
        const result = findUnsetRequiredFields(activeFields, fields, data, makeCallbacks({ required: ["name"] }));
        expect(result.has("name")).toBe(false);
    });

    test("never flags boolean fields regardless of required", () => {
        const activeFields = { active: {} };
        const data = { active: false };
        const result = findUnsetRequiredFields(activeFields, fields, data, makeCallbacks({ required: ["active"] }));
        expect(result.has("active")).toBe(false);
    });

    test("never flags float fields regardless of required", () => {
        const activeFields = { amount: {} };
        const data = { amount: 0 };
        const result = findUnsetRequiredFields(activeFields, fields, data, makeCallbacks({ required: ["amount"] }));
        expect(result.has("amount")).toBe(false);
    });

    test("never flags integer fields regardless of required", () => {
        const activeFields = { qty: {} };
        const data = { qty: 0 };
        const result = findUnsetRequiredFields(activeFields, fields, data, makeCallbacks({ required: ["qty"] }));
        expect(result.has("qty")).toBe(false);
    });

    test("never flags monetary fields regardless of required", () => {
        const activeFields = { price: {} };
        const data = { price: 0 };
        const result = findUnsetRequiredFields(activeFields, fields, data, makeCallbacks({ required: ["price"] }));
        expect(result.has("price")).toBe(false);
    });

    test("skips invisible fields even when required and unset", () => {
        const activeFields = { name: {} };
        const data = { name: false };
        const result = findUnsetRequiredFields(
            activeFields, fields, data,
            makeCallbacks({ required: ["name"], invisible: ["name"] }),
        );
        expect(result.has("name")).toBe(false);
    });

    test("multiple required fields — flags only unset ones", () => {
        const activeFields = { name: {}, description: {} };
        const data = { name: "has value", description: false };
        const result = findUnsetRequiredFields(
            activeFields, fields, data,
            makeCallbacks({ required: ["name", "description"] }),
        );
        expect(result.has("name")).toBe(false);
        expect(result.has("description")).toBe(true);
    });
});

// ---------------------------------------------------------------------------
// findUnsetRequiredFields — html field
// ---------------------------------------------------------------------------

describe("findUnsetRequiredFields — html", () => {
    const fields = { body: { type: "html" } };

    test("flags required html when length is 0", () => {
        const activeFields = { body: {} };
        const data = { body: "" }; // length 0
        const result = findUnsetRequiredFields(activeFields, fields, data, makeCallbacks({ required: ["body"] }));
        expect(result.has("body")).toBe(true);
    });

    test("does not flag required html when content present", () => {
        const activeFields = { body: {} };
        const data = { body: "<p>Hello</p>" };
        const result = findUnsetRequiredFields(activeFields, fields, data, makeCallbacks({ required: ["body"] }));
        expect(result.has("body")).toBe(false);
    });

    test("does not flag non-required empty html", () => {
        const activeFields = { body: {} };
        const data = { body: "" };
        const result = findUnsetRequiredFields(activeFields, fields, data, makeCallbacks());
        expect(result.has("body")).toBe(false);
    });
});

// ---------------------------------------------------------------------------
// findUnsetRequiredFields — x2many fields
// ---------------------------------------------------------------------------

describe("findUnsetRequiredFields — x2many", () => {
    const fields = {
        line_ids: { type: "one2many" },
        tag_ids: { type: "many2many" },
    };

    test("flags required one2many when count is 0", () => {
        const activeFields = { line_ids: {} };
        const data = { line_ids: { count: 0 } };
        const result = findUnsetRequiredFields(activeFields, fields, data, makeCallbacks({ required: ["line_ids"] }));
        expect(result.has("line_ids")).toBe(true);
    });

    test("does not flag required one2many when count > 0", () => {
        const activeFields = { line_ids: {} };
        const data = { line_ids: { count: 2 } };
        const result = findUnsetRequiredFields(activeFields, fields, data, makeCallbacks({ required: ["line_ids"] }));
        expect(result.has("line_ids")).toBe(false);
    });

    test("flags x2many with invalid children even when not required", () => {
        const activeFields = { line_ids: {} };
        const data = { line_ids: { count: 3 } };
        const result = findUnsetRequiredFields(
            activeFields, fields, data,
            makeCallbacks({ invalidLists: ["line_ids"] }),
        );
        expect(result.has("line_ids")).toBe(true);
    });

    test("flags required many2many when count is 0", () => {
        const activeFields = { tag_ids: {} };
        const data = { tag_ids: { count: 0 } };
        const result = findUnsetRequiredFields(activeFields, fields, data, makeCallbacks({ required: ["tag_ids"] }));
        expect(result.has("tag_ids")).toBe(true);
    });
});

// ---------------------------------------------------------------------------
// findUnsetRequiredFields — json field
// ---------------------------------------------------------------------------

describe("findUnsetRequiredFields — json", () => {
    const fields = { metadata: { type: "json" } };

    test("flags required json when null", () => {
        const activeFields = { metadata: {} };
        const data = { metadata: null };
        const result = findUnsetRequiredFields(activeFields, fields, data, makeCallbacks({ required: ["metadata"] }));
        expect(result.has("metadata")).toBe(true);
    });

    test("flags required json when empty object", () => {
        const activeFields = { metadata: {} };
        const data = { metadata: {} };
        const result = findUnsetRequiredFields(activeFields, fields, data, makeCallbacks({ required: ["metadata"] }));
        expect(result.has("metadata")).toBe(true);
    });

    test("does not flag required json when has content", () => {
        const activeFields = { metadata: {} };
        const data = { metadata: { key: "value" } };
        const result = findUnsetRequiredFields(activeFields, fields, data, makeCallbacks({ required: ["metadata"] }));
        expect(result.has("metadata")).toBe(false);
    });

    test("does not flag non-required empty json", () => {
        const activeFields = { metadata: {} };
        const data = { metadata: null };
        const result = findUnsetRequiredFields(activeFields, fields, data, makeCallbacks());
        expect(result.has("metadata")).toBe(false);
    });
});

// ---------------------------------------------------------------------------
// findUnsetRequiredFields — properties field
// ---------------------------------------------------------------------------

describe("findUnsetRequiredFields — properties", () => {
    const fields = { properties: { type: "properties" } };

    test("flags properties field when any definition has empty name", () => {
        const activeFields = { properties: {} };
        const data = {
            properties: [
                { name: "", string: "Label" },
                { name: "prop_a", string: "Prop A" },
            ],
        };
        const result = findUnsetRequiredFields(activeFields, fields, data, makeCallbacks());
        expect(result.has("properties")).toBe(true);
    });

    test("flags properties field when any definition has empty string", () => {
        const activeFields = { properties: {} };
        const data = {
            properties: [{ name: "prop_a", string: "" }],
        };
        const result = findUnsetRequiredFields(activeFields, fields, data, makeCallbacks());
        expect(result.has("properties")).toBe(true);
    });

    test("does not flag properties when all definitions have name and string", () => {
        const activeFields = { properties: {} };
        const data = {
            properties: [
                { name: "prop_a", string: "Prop A" },
                { name: "prop_b", string: "Prop B" },
            ],
        };
        const result = findUnsetRequiredFields(activeFields, fields, data, makeCallbacks());
        expect(result.has("properties")).toBe(false);
    });

    test("does not flag properties when value is falsy (no definitions yet)", () => {
        const activeFields = { properties: {} };
        const data = { properties: false };
        const result = findUnsetRequiredFields(activeFields, fields, data, makeCallbacks());
        expect(result.has("properties")).toBe(false);
    });

    test("skips relatedPropertyField", () => {
        const fieldsWithProp = {
            ...fields,
            derived_prop: { type: "char", relatedPropertyField: true },
        };
        const activeFields = { derived_prop: {} };
        const data = { derived_prop: false };
        const result = findUnsetRequiredFields(
            activeFields, fieldsWithProp, data,
            makeCallbacks({ required: ["derived_prop"] }),
        );
        // relatedPropertyField is always skipped
        expect(result.has("derived_prop")).toBe(false);
    });
});
