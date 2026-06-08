// @ts-check

/**
 * Pure unit tests for record_validator.js.
 *
 * Tests the required-field validation logic without OWL, DOM, or a mock server.
 * All callbacks (isInvisible, isRequired, isChildListValid) are plain functions.
 */

import { describe, expect, test } from "@odoo/hoot";
import {
    checkValidity,
    displayInvalidFieldNotification,
    findUnsetRequiredFields,
    removeInvalidFields,
    resetFieldValidity,
    setInvalidField,
} from "@web/model/relational_model/record_validator";

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

// ===========================================================================
// Orchestration helpers — added in Phase 2 of the model-layer decomposition
// (workspaces/workspace-LMMG/brainstorms/2026-05-23-web-model-layer-decomposition.md).
//
// These tests target the helpers directly with a hand-rolled mock record.
// The mock supplies only the surface each helper reads — invalidFields Set,
// unsetRequiredFields Set, model.hooks namespaces, multiEdit hooks, etc.
//
// Imports for these helpers live at the top of this file (consolidated with
// the existing findUnsetRequiredFields import) to satisfy ES-module
// top-level-import semantics.
// ===========================================================================

// ---------------------------------------------------------------------------
// Mock factory for orchestration tests
// ---------------------------------------------------------------------------

/**
 * Builds the minimum record shape consumed by the orchestration helpers.
 *
 * Defaults exercise the happy path:
 *   - no invalid fields, no unset required fields
 *   - hooks return undefined (allow), notification hook returns a no-op closer
 *   - not selected, multiEdit off
 *
 * @param {Object} [opts]
 * @param {Object} [opts.activeFields={}]
 * @param {Object} [opts.fields={}]
 * @param {Object} [opts.data={}]
 * @param {string[]} [opts.invalid=[]] - fields already in _invalidFields
 * @param {string[]} [opts.unsetRequired=[]] - fields already in _unsetRequiredFields
 * @param {string[]} [opts.required=[]] - which fields _isRequired returns true for
 * @param {string[]} [opts.invisible=[]] - which fields _isInvisible returns true for
 * @param {boolean} [opts.selected=false]
 * @param {boolean} [opts.multiEdit=false]
 * @param {*} [opts.willSetInvalidResult] - return value of onWillSetInvalidField
 * @param {Function|null} [opts.onDisplayInvalidFields] - notification hook stub
 * @returns {Object}
 */
function makeOrchestrationRecord({
    activeFields = {},
    fields = {},
    data = {},
    invalid = [],
    unsetRequired = [],
    required = [],
    invisible = [],
    selected = false,
    multiEdit = false,
    willSetInvalidResult = undefined,
    onDisplayInvalidFields = null,
} = {}) {
    /** @type {any} */
    const record = {
        activeFields,
        fields,
        data,
        selected,
        dirty: false,
        _invalidFields: new Set(invalid),
        _unsetRequiredFields: new Set(unsetRequired),
        _closeInvalidFieldsNotification: () => {},
        _isInvisible: (name) => invisible.includes(name),
        _isRequired: (name) => required.includes(name),
        // delegate to the imported helper so the recursive isChildListValid
        // codepath in checkValidity hits the same module under test
        _checkValidity(options) {
            return checkValidity(this, options);
        },
        discard: async () => {},
        switchMode: () => {},
        model: {
            multiEdit,
            root: { _recordToDiscard: null },
            hooks: {
                lifecycle: {
                    onWillSetInvalidField: () => willSetInvalidResult,
                },
                ui: {
                    onDisplayInvalidFields:
                        onDisplayInvalidFields ?? (() => () => {}),
                },
            },
        },
    };
    return record;
}

// ---------------------------------------------------------------------------
// checkValidity — silent mode
// ---------------------------------------------------------------------------

describe("checkValidity — silent mode", () => {
    test("returns true when no required fields are unset, without mutating state", () => {
        const rec = makeOrchestrationRecord({
            activeFields: { name: {} },
            fields: { name: { type: "char" } },
            data: { name: "Partner" },
            required: ["name"],
        });
        const result = checkValidity(rec, { silent: true });
        expect(result).toBe(true);
        // silent must not touch state
        expect(rec._invalidFields.size).toBe(0);
        expect(rec._unsetRequiredFields.size).toBe(0);
    });

    test("returns false when a required field is unset, without mutating state", () => {
        const rec = makeOrchestrationRecord({
            activeFields: { name: {} },
            fields: { name: { type: "char" } },
            data: { name: false },
            required: ["name"],
        });
        const result = checkValidity(rec, { silent: true });
        expect(result).toBe(false);
        // silent must not push the field into _invalidFields
        expect(rec._invalidFields.size).toBe(0);
        expect(rec._unsetRequiredFields.size).toBe(0);
    });
});

// ---------------------------------------------------------------------------
// checkValidity — default mode (replace unsetRequired subset)
// ---------------------------------------------------------------------------

describe("checkValidity — default mode", () => {
    test("populates _invalidFields and _unsetRequiredFields when a required field is unset", () => {
        const rec = makeOrchestrationRecord({
            activeFields: { name: {} },
            fields: { name: { type: "char" } },
            data: { name: false },
            required: ["name"],
        });
        const result = checkValidity(rec);
        expect(result).toBe(false);
        expect([...rec._invalidFields]).toEqual(["name"]);
        expect([...rec._unsetRequiredFields]).toEqual(["name"]);
    });

    test("replaces the prior _unsetRequiredFields subset on rescan", () => {
        // Prior state: "name" was unset
        const rec = makeOrchestrationRecord({
            activeFields: { name: {}, email: {} },
            fields: { name: { type: "char" }, email: { type: "char" } },
            data: { name: "now set", email: false },
            required: ["name", "email"],
            invalid: ["name"],
            unsetRequired: ["name"],
        });
        const result = checkValidity(rec);
        expect(result).toBe(false);
        // "name" should have been pruned from both sets; "email" added
        expect([...rec._invalidFields]).toEqual(["email"]);
        expect([...rec._unsetRequiredFields]).toEqual(["email"]);
    });

    test("preserves invalid-input flags (not in unsetRequiredFields) across the rescan", () => {
        // "name" was flagged as invalid by a field widget (e.g. via setInvalidField),
        // not because it was unset-required. checkValidity should leave it alone.
        const rec = makeOrchestrationRecord({
            activeFields: { name: {}, email: {} },
            fields: { name: { type: "char" }, email: { type: "char" } },
            data: { name: "set", email: "set" },
            required: [],
            invalid: ["name"],          // invalid-input flag survives
            unsetRequired: [],          // but not in unset-required subset
        });
        checkValidity(rec);
        expect([...rec._invalidFields]).toEqual(["name"]);
    });
});

// ---------------------------------------------------------------------------
// checkValidity — removeInvalidOnly mode (prune-only)
// ---------------------------------------------------------------------------

describe("checkValidity — removeInvalidOnly mode", () => {
    test("removes fields from _unsetRequiredFields that are no longer unset, without adding new ones", () => {
        // Prior: "name" was unset; now set. "email" is unset but not in the prior subset.
        const rec = makeOrchestrationRecord({
            activeFields: { name: {}, email: {} },
            fields: { name: { type: "char" }, email: { type: "char" } },
            data: { name: "now set", email: false },
            required: ["name", "email"],
            invalid: ["name"],
            unsetRequired: ["name"],
        });
        checkValidity(rec, { removeInvalidOnly: true });
        // "name" pruned (no longer unset); "email" NOT added (removeInvalidOnly).
        expect([...rec._invalidFields]).toEqual([]);
        expect([...rec._unsetRequiredFields]).toEqual([]);
    });
});

// ---------------------------------------------------------------------------
// checkValidity — displayNotification side effect
// ---------------------------------------------------------------------------

describe("checkValidity — displayNotification", () => {
    test("invokes onDisplayInvalidFields when invalid and displayNotification=true", () => {
        let displayCalled = false;
        const rec = makeOrchestrationRecord({
            activeFields: { name: {} },
            fields: { name: { type: "char" } },
            data: { name: false },
            required: ["name"],
            onDisplayInvalidFields: () => {
                displayCalled = true;
                return () => {};
            },
        });
        checkValidity(rec, { displayNotification: true });
        expect(displayCalled).toBe(true);
    });

    test("does NOT invoke onDisplayInvalidFields when valid", () => {
        let displayCalled = false;
        const rec = makeOrchestrationRecord({
            activeFields: { name: {} },
            fields: { name: { type: "char" } },
            data: { name: "set" },
            onDisplayInvalidFields: () => {
                displayCalled = true;
                return () => {};
            },
        });
        checkValidity(rec, { displayNotification: true });
        expect(displayCalled).toBe(false);
    });

    test("stores the close callback on record._closeInvalidFieldsNotification", () => {
        const closer = () => {};
        const rec = makeOrchestrationRecord({
            activeFields: { name: {} },
            fields: { name: { type: "char" } },
            data: { name: false },
            required: ["name"],
            onDisplayInvalidFields: () => closer,
        });
        checkValidity(rec, { displayNotification: true });
        expect(rec._closeInvalidFieldsNotification).toBe(closer);
    });
});

// ---------------------------------------------------------------------------
// setInvalidField
// ---------------------------------------------------------------------------

describe("setInvalidField", () => {
    test("adds the field name to _invalidFields", async () => {
        const rec = makeOrchestrationRecord();
        await setInvalidField(rec, "name");
        expect(rec._invalidFields.has("name")).toBe(true);
    });

    test("is idempotent — adding the same field twice does not duplicate", async () => {
        const rec = makeOrchestrationRecord({ invalid: ["name"] });
        await setInvalidField(rec, "name");
        expect(rec._invalidFields.size).toBe(1);
    });

    test("returns early without adding when onWillSetInvalidField returns false", async () => {
        const rec = makeOrchestrationRecord({ willSetInvalidResult: false });
        await setInvalidField(rec, "name");
        expect(rec._invalidFields.size).toBe(0);
    });

    test("multiEdit + selected: triggers discard + switchMode + notification", async () => {
        let discardCalled = false;
        let switchModeArg = null;
        let displayCalled = false;
        const rec = makeOrchestrationRecord({
            selected: true,
            multiEdit: true,
            onDisplayInvalidFields: () => {
                displayCalled = true;
                return () => {};
            },
        });
        rec.discard = async () => {
            discardCalled = true;
        };
        rec.switchMode = (mode) => {
            switchModeArg = mode;
        };
        await setInvalidField(rec, "name");
        expect(displayCalled).toBe(true);
        expect(discardCalled).toBe(true);
        expect(switchModeArg).toBe("readonly");
    });

    test("multiEdit + selected + _recordToDiscard === this: does NOT trigger discard/switchMode", async () => {
        let discardCalled = false;
        const rec = makeOrchestrationRecord({
            selected: true,
            multiEdit: true,
        });
        rec.model.root._recordToDiscard = rec;
        rec.discard = async () => {
            discardCalled = true;
        };
        await setInvalidField(rec, "name");
        // The field is still flagged, but the multiEdit cascade is suppressed
        // because this record is the one already being discarded.
        expect(rec._invalidFields.has("name")).toBe(true);
        expect(discardCalled).toBe(false);
    });
});

// ---------------------------------------------------------------------------
// resetFieldValidity + removeInvalidFields
// ---------------------------------------------------------------------------

describe("resetFieldValidity", () => {
    test("removes the field name from _invalidFields", () => {
        const rec = makeOrchestrationRecord({ invalid: ["name", "email"] });
        resetFieldValidity(rec, "name");
        expect(rec._invalidFields.has("name")).toBe(false);
        expect(rec._invalidFields.has("email")).toBe(true);
    });

    test("is a no-op when the field is not flagged", () => {
        const rec = makeOrchestrationRecord({ invalid: ["email"] });
        resetFieldValidity(rec, "name");
        expect(rec._invalidFields.size).toBe(1);
    });

    test("does NOT touch _unsetRequiredFields", () => {
        const rec = makeOrchestrationRecord({
            invalid: ["name"],
            unsetRequired: ["name"],
        });
        resetFieldValidity(rec, "name");
        expect(rec._invalidFields.has("name")).toBe(false);
        // _unsetRequiredFields is the canonical source for "required not satisfied";
        // this helper is for invalid-input flag only.
        expect(rec._unsetRequiredFields.has("name")).toBe(true);
    });
});

describe("removeInvalidFields (bulk)", () => {
    test("removes multiple field names in one call", () => {
        const rec = makeOrchestrationRecord({ invalid: ["a", "b", "c"] });
        removeInvalidFields(rec, "a", "c");
        expect([...rec._invalidFields]).toEqual(["b"]);
    });

    test("is a no-op when no field names are passed", () => {
        const rec = makeOrchestrationRecord({ invalid: ["a", "b"] });
        removeInvalidFields(rec);
        expect(rec._invalidFields.size).toBe(2);
    });
});

// ---------------------------------------------------------------------------
// displayInvalidFieldNotification
// ---------------------------------------------------------------------------

describe("displayInvalidFieldNotification", () => {
    test("returns the close callback produced by the hook", () => {
        const closer = () => "closed";
        const rec = makeOrchestrationRecord({
            onDisplayInvalidFields: () => closer,
        });
        const result = displayInvalidFieldNotification(rec);
        expect(result).toBe(closer);
    });
});
