// @ts-check

/**
 * Pure unit tests for processProperties() (extracted in Phase 4 of the
 * model-layer decomposition plan;
 * workspaces/workspace-LMMG/brainstorms/2026-05-23-web-model-layer-decomposition.md).
 *
 * The helper splices per-property definitions into ``record.fields`` /
 * ``record.activeFields`` and shapes per-property values by type (m2m →
 * StaticList, m2o → value or "No Access" placeholder, scalars → pass-through).
 * The mock record exposes only what the helper reads: fields, activeFields,
 * _createStaticListDatapoint(data, fieldName).
 *
 * Integration coverage: tests/views/fields/properties_field.test.js.
 *
 * Module under test: model/relational_model/record_properties.js
 */

import { describe, expect, test } from "@odoo/hoot";
import { processProperties } from "@web/model/relational_model/record_properties";

// Mock factory

/**
 * Build a minimal record mock for processProperties tests.
 *
 * Defaults:
 *   - empty fields / activeFields (schema fresh-create path)
 *   - _createStaticListDatapoint returns a synthetic StaticList carrying
 *     its constructor arguments so tests can assert on them
 *
 * @param {Object} [opts]
 * @param {Object} [opts.fields={}] - pre-populated field definitions
 * @param {Object} [opts.activeFields={}] - pre-populated active fields
 * @param {Function|null} [opts.createStaticList]
 * @returns {Object}
 */
function makePropertyRecord({
    fields = {},
    activeFields = {},
    createStaticList = null,
} = {}) {
    /** @type {any} */
    const record = {
        fields,
        activeFields,
        _createStaticListDatapoint:
            createStaticList ??
            ((data, fieldName) => ({ data, fieldName, __isStaticList: true })),
    };
    return record;
}

// processProperties — empty input and schema splice basics

describe("processProperties — empty input and splice basics", () => {
    test("returns empty object when properties array is empty", () => {
        const rec = makePropertyRecord();
        const result = processProperties(rec, [], "props", false);
        expect(result).toEqual({});
        // No schema mutation when nothing to splice.
        expect(Object.keys(rec.fields)).toEqual([]);
        expect(Object.keys(rec.activeFields)).toEqual([]);
    });

    test("registers a synthetic field under ${fieldName}.${propertyName}", () => {
        const rec = makePropertyRecord();
        processProperties(
            rec,
            [{ name: "color", type: "char", value: "red" }],
            "props",
            false,
        );
        expect("props.color" in rec.fields).toBe(true);
        expect(rec.fields["props.color"].name).toBe("props.color");
        expect(rec.fields["props.color"].propertyName).toBe("color");
    });

    test("returns the per-property value under the composite key", () => {
        const rec = makePropertyRecord();
        const result = processProperties(
            rec,
            [{ name: "color", type: "char", value: "red" }],
            "props",
            false,
        );
        expect(result["props.color"]).toBe("red");
    });
});

// processProperties — sortable flag dispatch

describe("processProperties — sortable flag", () => {
    test("sortable=false for relational and tag types", () => {
        const rec = makePropertyRecord();
        processProperties(
            rec,
            [
                { name: "partner", type: "many2one", comodel: "res.partner" },
                { name: "tags", type: "many2many", comodel: "res.tag" },
                { name: "labels", type: "tags" },
            ],
            "props",
            false,
        );
        expect(rec.fields["props.partner"].sortable).toBe(false);
        expect(rec.fields["props.tags"].sortable).toBe(false);
        expect(rec.fields["props.labels"].sortable).toBe(false);
    });

    test("sortable=true for char, int, date, etc.", () => {
        const rec = makePropertyRecord();
        processProperties(
            rec,
            [
                { name: "name", type: "char" },
                { name: "count", type: "integer" },
                { name: "due", type: "date" },
            ],
            "props",
            false,
        );
        expect(rec.fields["props.name"].sortable).toBe(true);
        expect(rec.fields["props.count"].sortable).toBe(true);
        expect(rec.fields["props.due"].sortable).toBe(true);
    });
});

// processProperties — relation back-pointer

describe("processProperties — relatedPropertyField back-pointer", () => {
    test("field.relatedPropertyField names the parent field (no id/displayName here)", () => {
        const rec = makePropertyRecord();
        processProperties(rec, [{ name: "color", type: "char" }], "props", false);
        // The field-level pointer is for the SCHEMA — only the parent
        // field name. (The id/displayName are at the activeField level.)
        expect(rec.fields["props.color"].relatedPropertyField).toEqual({
            name: "props",
        });
    });

    test("activeField.relatedPropertyField carries parent id + displayName", () => {
        const rec = makePropertyRecord();
        const parent = { id: 7, display_name: "Definition Record" };
        processProperties(rec, [{ name: "color", type: "char" }], "props", parent);
        expect(rec.activeFields["props.color"].relatedPropertyField).toEqual({
            name: "props",
            id: 7,
            displayName: "Definition Record",
        });
    });

    test("parent=false: relatedPropertyField has undefined id and displayName", () => {
        const rec = makePropertyRecord();
        processProperties(rec, [{ name: "color", type: "char" }], "props", false);
        expect(rec.activeFields["props.color"].relatedPropertyField).toEqual({
            name: "props",
            id: undefined,
            displayName: undefined,
        });
    });
});

// processProperties — per-type value shaping

describe("processProperties — scalar value shaping", () => {
    test("scalar with defined value passes through", () => {
        const rec = makePropertyRecord();
        const result = processProperties(
            rec,
            [{ name: "count", type: "integer", value: 42 }],
            "props",
            false,
        );
        expect(result["props.count"]).toBe(42);
    });

    test("scalar with undefined value falls back to false", () => {
        const rec = makePropertyRecord();
        const result = processProperties(
            rec,
            [{ name: "label", type: "char" }], // no .value
            "props",
            false,
        );
        expect(result["props.label"]).toBe(false);
    });

    test("scalar with explicit null value falls back to false (?? semantics)", () => {
        const rec = makePropertyRecord();
        const result = processProperties(
            rec,
            [{ name: "label", type: "char", value: null }],
            "props",
            false,
        );
        expect(result["props.label"]).toBe(false);
    });
});

describe("processProperties — many2one value shaping", () => {
    test("normal m2o value passes through", () => {
        const rec = makePropertyRecord();
        const value = { id: 5, display_name: "Partner" };
        const result = processProperties(
            rec,
            [{ name: "partner", type: "many2one", value }],
            "props",
            false,
        );
        expect(result["props.partner"]).toBe(value);
    });

    test("display_name === null swaps to 'No Access' placeholder", () => {
        const rec = makePropertyRecord();
        const result = processProperties(
            rec,
            [
                {
                    name: "partner",
                    type: "many2one",
                    value: { id: 5, display_name: null },
                },
            ],
            "props",
            false,
        );
        // The id is preserved; the display_name is the translated placeholder.
        // toString() because _t() returns a LazyTranslatedString in some contexts.
        expect(result["props.partner"].id).toBe(5);
        expect(String(result["props.partner"].display_name)).toBe("No Access");
    });

    test("falsy m2o (value === false) passes through unchanged", () => {
        const rec = makePropertyRecord();
        const result = processProperties(
            rec,
            [{ name: "partner", type: "many2one", value: false }],
            "props",
            false,
        );
        expect(result["props.partner"]).toBe(false);
    });
});

describe("processProperties — many2many value shaping", () => {
    test("builds a new StaticList from server tuples [id, display_name]", () => {
        let captured = null;
        const rec = makePropertyRecord({
            createStaticList: (data, fieldName) => {
                captured = { data, fieldName };
                return { __isStaticList: true };
            },
        });
        processProperties(
            rec,
            [
                {
                    name: "tags",
                    type: "many2many",
                    comodel: "res.tag",
                    value: [
                        [1, "A"],
                        [2, "B"],
                    ],
                },
            ],
            "props",
            false,
        );
        expect(captured.fieldName).toBe("props.tags");
        // Server tuples are mapped to {id, display_name} objects.
        expect(captured.data).toEqual([
            { id: 1, display_name: "A" },
            { id: 2, display_name: "B" },
        ]);
    });

    test("treats undefined value as an empty list (no crash on .map)", () => {
        let captured = null;
        const rec = makePropertyRecord({
            createStaticList: (data, fieldName) => {
                captured = { data, fieldName };
                return { __isStaticList: true };
            },
        });
        processProperties(
            rec,
            [{ name: "tags", type: "many2many", comodel: "res.tag" }],
            "props",
            false,
        );
        expect(captured.data).toEqual([]);
    });

    test("reuses an existing StaticList from currentValues (does not recreate)", () => {
        let createCalled = false;
        const existing = { __isStaticList: true, marker: "existing" };
        const rec = makePropertyRecord({
            createStaticList: () => {
                createCalled = true;
                return { __isStaticList: true };
            },
        });
        const result = processProperties(
            rec,
            [
                {
                    name: "tags",
                    type: "many2many",
                    comodel: "res.tag",
                    value: [[1, "A"]],
                },
            ],
            "props",
            false,
            { "props.tags": existing },
        );
        expect(createCalled).toBe(false);
        expect(result["props.tags"]).toBe(existing);
    });
});

// processProperties — hasCurrentValues schema-rewrite toggle

describe("processProperties — schema-rewrite gating by hasCurrentValues", () => {
    test("no currentValues + field already exists: schema is NOT overwritten", () => {
        const existingFieldDef = {
            name: "props.color",
            type: "char",
            patched_by_consumer: true, // marker we expect to survive
        };
        const rec = makePropertyRecord({
            fields: { "props.color": existingFieldDef },
        });
        processProperties(
            rec,
            [{ name: "color", type: "char", value: "red" }],
            "props",
            false,
            // no currentValues → initial-load path
        );
        // Original field def survives — the marker is intact.
        expect(rec.fields["props.color"]).toBe(existingFieldDef);
        expect(rec.fields["props.color"].patched_by_consumer).toBe(true);
    });

    test("non-empty currentValues + field exists: schema IS overwritten", () => {
        const existingFieldDef = {
            name: "props.color",
            type: "char",
            patched_by_consumer: true,
        };
        const rec = makePropertyRecord({
            fields: { "props.color": existingFieldDef },
        });
        processProperties(
            rec,
            [{ name: "color", type: "char", value: "red" }],
            "props",
            false,
            // Non-empty currentValues → change-driven path → schema rewrite.
            { "props.other": "unrelated existing value" },
        );
        // A new field object replaced the existing one — the marker is GONE.
        expect(rec.fields["props.color"]).not.toBe(existingFieldDef);
        expect(rec.fields["props.color"].patched_by_consumer).toBe(undefined);
    });
});

// processProperties — combined return shape

describe("processProperties — combined return", () => {
    test("returns a flat bag keyed by composite name across mixed property types", () => {
        const rec = makePropertyRecord();
        const result = processProperties(
            rec,
            [
                { name: "color", type: "char", value: "red" },
                { name: "count", type: "integer", value: 7 },
                {
                    name: "partner",
                    type: "many2one",
                    value: { id: 1, display_name: "X" },
                },
                {
                    name: "tags",
                    type: "many2many",
                    comodel: "res.tag",
                    value: [[1, "A"]],
                },
            ],
            "props",
            false,
        );
        expect(Object.keys(result).sort()).toEqual([
            "props.color",
            "props.count",
            "props.partner",
            "props.tags",
        ]);
        expect(result["props.color"]).toBe("red");
        expect(result["props.count"]).toBe(7);
        expect(result["props.partner"]).toEqual({ id: 1, display_name: "X" });
        expect(result["props.tags"].__isStaticList).toBe(true);
    });
});
