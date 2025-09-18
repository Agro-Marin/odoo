// @ts-check

/**
 * Pure unit tests for field_spec.js.
 *
 * Tests getFieldsSpec which builds the server fetch specification
 * from active fields. No OWL or DOM needed.
 */

import { describe, expect, test } from "@odoo/hoot";
import { getFieldsSpec } from "@web/model/relational_model/field_spec";
import { makeActiveField } from "@web/model/relational_model/field_metadata";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Build minimal activeFields from a list of [name, options] pairs. */
function makeActiveFields(defs) {
    const activeFields = {};
    for (const [name, opts] of defs) {
        activeFields[name] = makeActiveField(opts || {});
    }
    return activeFields;
}

// ---------------------------------------------------------------------------
// Scalar fields
// ---------------------------------------------------------------------------

describe("getFieldsSpec — scalar fields", () => {
    test("char field produces empty spec object", () => {
        const activeFields = makeActiveFields([["name", {}]]);
        const fields = { name: { type: "char" } };
        const result = getFieldsSpec(activeFields, fields, {});
        expect(result.name).toEqual({});
    });

    test("integer field produces empty spec object", () => {
        const activeFields = makeActiveFields([["qty", {}]]);
        const fields = { qty: { type: "integer" } };
        const result = getFieldsSpec(activeFields, fields, {});
        expect(result.qty).toEqual({});
    });

    test("boolean field produces empty spec object", () => {
        const activeFields = makeActiveFields([["active", {}]]);
        const fields = { active: { type: "boolean" } };
        const result = getFieldsSpec(activeFields, fields, {});
        expect(result.active).toEqual({});
    });

    test("skips relatedPropertyField", () => {
        const activeFields = makeActiveFields([["derived", {}]]);
        const fields = { derived: { type: "char", relatedPropertyField: true } };
        const result = getFieldsSpec(activeFields, fields, {});
        expect("derived" in result).toBe(false);
    });
});

// ---------------------------------------------------------------------------
// many2one / reference
// ---------------------------------------------------------------------------

describe("getFieldsSpec — many2one", () => {
    test("includes display_name in fields", () => {
        const activeFields = makeActiveFields([["partner_id", {}]]);
        const fields = { partner_id: { type: "many2one" } };
        const result = getFieldsSpec(activeFields, fields, {});
        expect(result.partner_id.fields.display_name).toEqual({});
    });

    test("does not include display_name when always invisible", () => {
        const activeFields = { partner_id: makeActiveField({ invisible: true }) };
        const fields = { partner_id: { type: "many2one" } };
        const result = getFieldsSpec(activeFields, fields, {});
        // Always invisible → only { fields: {} }
        expect(Object.keys(result.partner_id.fields).length).toBe(0);
    });

    test("includes related fields when provided and not invisible", () => {
        const activeFields = {
            partner_id: {
                ...makeActiveField({}),
                related: {
                    activeFields: { name: makeActiveField({}) },
                    fields: { name: { type: "char" } },
                },
            },
        };
        const fields = { partner_id: { type: "many2one" } };
        const result = getFieldsSpec(activeFields, fields, {});
        expect("name" in result.partner_id.fields).toBe(true);
        expect("display_name" in result.partner_id.fields).toBe(true);
    });
});

describe("getFieldsSpec — reference", () => {
    test("includes display_name like many2one", () => {
        const activeFields = makeActiveFields([["category", {}]]);
        const fields = { category: { type: "reference" } };
        const result = getFieldsSpec(activeFields, fields, {});
        expect(result.category.fields.display_name).toEqual({});
    });
});

// ---------------------------------------------------------------------------
// x2many
// ---------------------------------------------------------------------------

describe("getFieldsSpec — one2many / many2many", () => {
    test("empty spec when no related defined", () => {
        const activeFields = makeActiveFields([["line_ids", {}]]);
        const fields = { line_ids: { type: "one2many" } };
        const result = getFieldsSpec(activeFields, fields, {});
        expect(result.line_ids).toEqual({});
    });

    test("includes nested fields spec when related defined and not invisible", () => {
        const activeFields = {
            line_ids: {
                ...makeActiveField({}),
                related: {
                    activeFields: { name: makeActiveField({}) },
                    fields: { name: { type: "char" } },
                },
                limit: 40,
            },
        };
        const fields = { line_ids: { type: "one2many" } };
        const result = getFieldsSpec(activeFields, fields, {});
        expect(result.line_ids.fields.name).toEqual({});
        expect(result.line_ids.limit).toBe(40);
    });

    test("skips related when always invisible", () => {
        const activeFields = {
            tag_ids: {
                ...makeActiveField({ invisible: true }),
                related: {
                    activeFields: { name: makeActiveField({}) },
                    fields: { name: { type: "char" } },
                },
            },
        };
        const fields = { tag_ids: { type: "many2many" } };
        const result = getFieldsSpec(activeFields, fields, {});
        expect(result.tag_ids).toEqual({});
    });

    test("includes always-invisible related when withInvisible option is true", () => {
        const activeFields = {
            tag_ids: {
                ...makeActiveField({ invisible: true }),
                related: {
                    activeFields: { name: makeActiveField({}) },
                    fields: { name: { type: "char" } },
                },
                limit: 10,
            },
        };
        const fields = { tag_ids: { type: "many2many" } };
        const result = getFieldsSpec(activeFields, fields, {}, { withInvisible: true });
        expect("fields" in result.tag_ids).toBe(true);
    });

    test("includes order from defaultOrderBy", () => {
        const activeFields = {
            line_ids: {
                ...makeActiveField({}),
                related: {
                    activeFields: { name: makeActiveField({}) },
                    fields: { name: { type: "char" } },
                },
                defaultOrderBy: [{ name: "name", asc: true }],
            },
        };
        const fields = { line_ids: { type: "one2many" } };
        const result = getFieldsSpec(activeFields, fields, {});
        expect(result.line_ids.order).toBe("name ASC");
    });
});

// ---------------------------------------------------------------------------
// properties
// ---------------------------------------------------------------------------

describe("getFieldsSpec — properties", () => {
    test("adds display_name to definition_record field spec", () => {
        const activeFields = {
            properties: makeActiveField({}),
            task_id: makeActiveField({}),
        };
        const fields = {
            properties: { type: "properties", definition_record: "task_id" },
            task_id: { type: "many2one" },
        };
        const result = getFieldsSpec(activeFields, fields, {});
        // task_id is many2one, so it has fields.display_name already
        // The properties handler adds display_name to the definition record spec
        expect("display_name" in result.task_id.fields).toBe(true);
    });
});
