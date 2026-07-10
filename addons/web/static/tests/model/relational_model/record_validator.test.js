// @ts-check

/**
 * Pure unit tests for record_validator.js.
 *
 * Tests the required-field validation logic without OWL, DOM, or a mock server.
 * All callbacks (isInvisible, isRequired, isChildListValid) are plain functions.
 */

import { describe, expect, test } from "@odoo/hoot";
import {
    computeRevalidationScope,
    extractFieldNamesFromExpr,
    getModifierDependencies,
    isFieldRequired,
} from "@web/model/relational_model/record_utils";
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
        const result = findUnsetRequiredFields(
            activeFields,
            fields,
            data,
            makeCallbacks(),
        );
        expect(result.size).toBe(0);
    });

    test("flags required char field when value is false", () => {
        const activeFields = { name: {} };
        const data = { name: false };
        const result = findUnsetRequiredFields(
            activeFields,
            fields,
            data,
            makeCallbacks({ required: ["name"] }),
        );
        expect(result.has("name")).toBe(true);
    });

    test("does not flag required char field when value is set", () => {
        const activeFields = { name: {} };
        const data = { name: "Partner" };
        const result = findUnsetRequiredFields(
            activeFields,
            fields,
            data,
            makeCallbacks({ required: ["name"] }),
        );
        expect(result.has("name")).toBe(false);
    });

    test("never flags boolean fields regardless of required", () => {
        const activeFields = { active: {} };
        const data = { active: false };
        const result = findUnsetRequiredFields(
            activeFields,
            fields,
            data,
            makeCallbacks({ required: ["active"] }),
        );
        expect(result.has("active")).toBe(false);
    });

    test("never flags float fields regardless of required", () => {
        const activeFields = { amount: {} };
        const data = { amount: 0 };
        const result = findUnsetRequiredFields(
            activeFields,
            fields,
            data,
            makeCallbacks({ required: ["amount"] }),
        );
        expect(result.has("amount")).toBe(false);
    });

    test("never flags integer fields regardless of required", () => {
        const activeFields = { qty: {} };
        const data = { qty: 0 };
        const result = findUnsetRequiredFields(
            activeFields,
            fields,
            data,
            makeCallbacks({ required: ["qty"] }),
        );
        expect(result.has("qty")).toBe(false);
    });

    test("never flags monetary fields regardless of required", () => {
        const activeFields = { price: {} };
        const data = { price: 0 };
        const result = findUnsetRequiredFields(
            activeFields,
            fields,
            data,
            makeCallbacks({ required: ["price"] }),
        );
        expect(result.has("price")).toBe(false);
    });

    test("skips invisible fields even when required and unset", () => {
        const activeFields = { name: {} };
        const data = { name: false };
        const result = findUnsetRequiredFields(
            activeFields,
            fields,
            data,
            makeCallbacks({ required: ["name"], invisible: ["name"] }),
        );
        expect(result.has("name")).toBe(false);
    });

    test("multiple required fields — flags only unset ones", () => {
        const activeFields = { name: {}, description: {} };
        const data = { name: "has value", description: false };
        const result = findUnsetRequiredFields(
            activeFields,
            fields,
            data,
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
        const result = findUnsetRequiredFields(
            activeFields,
            fields,
            data,
            makeCallbacks({ required: ["body"] }),
        );
        expect(result.has("body")).toBe(true);
    });

    test("does not flag required html when content present", () => {
        const activeFields = { body: {} };
        const data = { body: "<p>Hello</p>" };
        const result = findUnsetRequiredFields(
            activeFields,
            fields,
            data,
            makeCallbacks({ required: ["body"] }),
        );
        expect(result.has("body")).toBe(false);
    });

    test("does not flag non-required empty html", () => {
        const activeFields = { body: {} };
        const data = { body: "" };
        const result = findUnsetRequiredFields(
            activeFields,
            fields,
            data,
            makeCallbacks(),
        );
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
        const result = findUnsetRequiredFields(
            activeFields,
            fields,
            data,
            makeCallbacks({ required: ["line_ids"] }),
        );
        expect(result.has("line_ids")).toBe(true);
    });

    test("does not flag required one2many when count > 0", () => {
        const activeFields = { line_ids: {} };
        const data = { line_ids: { count: 2 } };
        const result = findUnsetRequiredFields(
            activeFields,
            fields,
            data,
            makeCallbacks({ required: ["line_ids"] }),
        );
        expect(result.has("line_ids")).toBe(false);
    });

    test("flags x2many with invalid children even when not required", () => {
        const activeFields = { line_ids: {} };
        const data = { line_ids: { count: 3 } };
        const result = findUnsetRequiredFields(
            activeFields,
            fields,
            data,
            makeCallbacks({ invalidLists: ["line_ids"] }),
        );
        expect(result.has("line_ids")).toBe(true);
    });

    test("flags required many2many when count is 0", () => {
        const activeFields = { tag_ids: {} };
        const data = { tag_ids: { count: 0 } };
        const result = findUnsetRequiredFields(
            activeFields,
            fields,
            data,
            makeCallbacks({ required: ["tag_ids"] }),
        );
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
        const result = findUnsetRequiredFields(
            activeFields,
            fields,
            data,
            makeCallbacks({ required: ["metadata"] }),
        );
        expect(result.has("metadata")).toBe(true);
    });

    test("flags required json when empty object", () => {
        const activeFields = { metadata: {} };
        const data = { metadata: {} };
        const result = findUnsetRequiredFields(
            activeFields,
            fields,
            data,
            makeCallbacks({ required: ["metadata"] }),
        );
        expect(result.has("metadata")).toBe(true);
    });

    test("does not flag required json when has content", () => {
        const activeFields = { metadata: {} };
        const data = { metadata: { key: "value" } };
        const result = findUnsetRequiredFields(
            activeFields,
            fields,
            data,
            makeCallbacks({ required: ["metadata"] }),
        );
        expect(result.has("metadata")).toBe(false);
    });

    test("does not flag non-required empty json", () => {
        const activeFields = { metadata: {} };
        const data = { metadata: null };
        const result = findUnsetRequiredFields(
            activeFields,
            fields,
            data,
            makeCallbacks(),
        );
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
        const result = findUnsetRequiredFields(
            activeFields,
            fields,
            data,
            makeCallbacks(),
        );
        expect(result.has("properties")).toBe(true);
    });

    test("flags properties field when any definition has empty string", () => {
        const activeFields = { properties: {} };
        const data = {
            properties: [{ name: "prop_a", string: "" }],
        };
        const result = findUnsetRequiredFields(
            activeFields,
            fields,
            data,
            makeCallbacks(),
        );
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
        const result = findUnsetRequiredFields(
            activeFields,
            fields,
            data,
            makeCallbacks(),
        );
        expect(result.has("properties")).toBe(false);
    });

    test("does not flag properties when value is falsy (no definitions yet)", () => {
        const activeFields = { properties: {} };
        const data = { properties: false };
        const result = findUnsetRequiredFields(
            activeFields,
            fields,
            data,
            makeCallbacks(),
        );
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
            activeFields,
            fieldsWithProp,
            data,
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
            // narrow record-facing interface of DynamicList (see dynamic_list.js)
            root: {
                _recordToDiscard: null,
                _isRecordToDiscard(rec) {
                    return this._recordToDiscard === rec;
                },
            },
            hooks: {
                lifecycle: {
                    onWillSetInvalidField: () => willSetInvalidResult,
                },
                ui: {
                    onDisplayInvalidFields: onDisplayInvalidFields ?? (() => () => {}),
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
            invalid: ["name"], // invalid-input flag survives
            unsetRequired: [], // but not in unset-required subset
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

    test("multiEdit + selected + record being discarded: does NOT trigger discard/switchMode", async () => {
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

// ===========================================================================
// Scoped per-commit re-validation (change-scoped-validation perf fix)
// ===========================================================================

// ---------------------------------------------------------------------------
// extractFieldNamesFromExpr — free-variable extraction from modifier exprs
// ---------------------------------------------------------------------------

describe("extractFieldNamesFromExpr", () => {
    test("returns empty set for falsy / boolean-literal modifiers", () => {
        expect([...extractFieldNamesFromExpr(false)]).toEqual([]);
        expect([...extractFieldNamesFromExpr(undefined)]).toEqual([]);
        expect([...extractFieldNamesFromExpr("True")]).toEqual([]);
        expect([...extractFieldNamesFromExpr("False")]).toEqual([]);
        expect([...extractFieldNamesFromExpr("1")]).toEqual([]);
        expect([...extractFieldNamesFromExpr("0")]).toEqual([]);
    });

    test("extracts field names from a comparison expression", () => {
        const names = extractFieldNamesFromExpr("state == 'done'");
        expect([...names]).toEqual(["state"]);
    });

    test("extracts multiple field names across boolean operators", () => {
        const names = extractFieldNamesFromExpr("a == 1 and b in (2, 3) or c");
        expect(new Set(names)).toEqual(new Set(["a", "b", "c"]));
    });

    test("collapses attribute access to its base name (parent.state -> parent)", () => {
        const names = extractFieldNamesFromExpr("parent.state == 'x'");
        expect([...names]).toEqual(["parent"]);
    });

    test("collapses context access to its base name (context.foo -> context)", () => {
        const names = extractFieldNamesFromExpr("context.foo and bar");
        expect(new Set(names)).toEqual(new Set(["context", "bar"]));
    });

    test("returns null (unknown) for an unparseable expression", () => {
        // Unbalanced parenthesis: py tokenizer/parser throws -> conservative null.
        expect(extractFieldNamesFromExpr("a ==")).toBe(null);
    });
});

// ---------------------------------------------------------------------------
// getModifierDependencies / computeRevalidationScope
// ---------------------------------------------------------------------------

describe("computeRevalidationScope", () => {
    test("scope of a change is the changed field plus its modifier dependents", () => {
        const activeFields = {
            a: {},
            b: { required: "a == 1" }, // b depends on a
            c: { required: "d == 2" }, // c depends on d, not a
            d: {},
        };
        const scope = computeRevalidationScope(["a"], activeFields);
        expect(scope.has("a")).toBe(true); // the changed field itself
        expect(scope.has("b")).toBe(true); // dependent via required modifier
        expect(scope.has("c")).toBe(false); // independent of a
    });

    test("invisible and readonly modifiers also create dependencies", () => {
        const activeFields = {
            a: {},
            b: { invisible: "a == 1" },
            c: { readonly: "a == 2" },
        };
        const scope = computeRevalidationScope(["a"], activeFields);
        expect(scope.has("b")).toBe(true);
        expect(scope.has("c")).toBe(true);
    });

    test("parent.* / context.* references do not create same-record dependencies", () => {
        const activeFields = {
            a: {},
            b: { required: "parent.state == 1" },
            c: { required: "context.foo == 2" },
        };
        const scope = computeRevalidationScope(["a"], activeFields);
        expect(scope.has("b")).toBe(false);
        expect(scope.has("c")).toBe(false);
    });

    test("fields with an unparseable modifier are always in scope (fallback)", () => {
        const activeFields = {
            a: {},
            b: { required: "a ==" }, // unparseable -> always revalidate
        };
        const scope = computeRevalidationScope(["z_unrelated"], activeFields);
        expect(scope.has("b")).toBe(true);
    });

    test("memoises the dependency map per activeFields object", () => {
        const activeFields = { a: {}, b: { required: "a == 1" } };
        const first = getModifierDependencies(activeFields);
        const second = getModifierDependencies(activeFields);
        expect(first).toBe(second); // same cached object (WeakMap keyed on activeFields)
    });
});

// ---------------------------------------------------------------------------
// checkValidity — scoped removeInvalidOnly: modifier re-evaluation
// ---------------------------------------------------------------------------

/**
 * Wrap makeOrchestrationRecord so that _isRequired / _isInvisible evaluate the
 * real modifier expressions declared on activeFields (via record_utils), and
 * count how many times each field's required modifier is evaluated.
 */
function makeModifierCountingRecord({
    activeFields,
    fields,
    data,
    unsetRequired = [],
}) {
    const requiredEvalCount = {};
    /** @type {any} */
    const rec = makeOrchestrationRecord({
        activeFields,
        fields,
        data,
        unsetRequired,
        invalid: unsetRequired,
    });
    const evalContext = data;
    rec._isRequired = (name) => {
        requiredEvalCount[name] = (requiredEvalCount[name] || 0) + 1;
        return isFieldRequired(activeFields[name], evalContext);
    };
    rec._isInvisible = (name) =>
        activeFields[name].invisible
            ? isFieldRequired({ required: activeFields[name].invisible }, evalContext)
            : false;
    return { rec, requiredEvalCount };
}

describe("checkValidity — scoped removeInvalidOnly (modifier evaluation)", () => {
    test("(4a) committing A does NOT re-evaluate B's required modifier when B doesn't reference A", () => {
        const activeFields = {
            a: {},
            b: { required: "c == 1" }, // B references C, not A
        };
        const fields = {
            a: { type: "char" },
            b: { type: "char" },
            c: { type: "char" },
        };
        // B is currently unset+required (c==1 holds, b is false) -> flagged.
        const data = { a: "set", b: false, c: 1 };
        const { rec, requiredEvalCount } = makeModifierCountingRecord({
            activeFields,
            fields,
            data,
            unsetRequired: ["b"],
        });
        // Commit A: scope is {a} (+ its dependents). B depends on C, so B is
        // out of scope and must NOT be re-evaluated.
        const scopedFields = computeRevalidationScope(["a"], activeFields);
        checkValidity(rec, { removeInvalidOnly: true, scopedFields });
        expect(requiredEvalCount["b"] || 0).toBe(0);
        // B stays flagged (nothing pruned it).
        expect(rec._unsetRequiredFields.has("b")).toBe(true);
    });

    test("(4b) committing A DOES re-evaluate B's required modifier when B references A", () => {
        const activeFields = {
            a: {},
            b: { required: "a == 1" }, // B references A
        };
        const fields = { a: { type: "char" }, b: { type: "char" } };
        // Start: a==1 so B required and unset -> flagged. After commit, a is now
        // 0 so B is no longer required -> B must be re-evaluated and pruned.
        const data = { a: 0, b: false };
        const { rec, requiredEvalCount } = makeModifierCountingRecord({
            activeFields,
            fields,
            data,
            unsetRequired: ["b"],
        });
        const scopedFields = computeRevalidationScope(["a"], activeFields);
        checkValidity(rec, { removeInvalidOnly: true, scopedFields });
        expect(requiredEvalCount["b"] || 0).toBeGreaterThan(0);
        // a == 1 is false now -> B not required -> pruned.
        expect(rec._unsetRequiredFields.has("b")).toBe(false);
        expect(rec._invalidFields.has("b")).toBe(false);
    });
});

// ---------------------------------------------------------------------------
// checkValidity — scoped removeInvalidOnly: x2many child re-validation
// ---------------------------------------------------------------------------

/** Build a mock child record datapoint with a _checkValidity spy. */
function makeChildRecord({ valid, dirty = true }) {
    let checkValidityCalls = 0;
    const child = {
        dirty,
        get isValid() {
            return valid;
        },
        _checkValidity() {
            checkValidityCalls++;
            return valid;
        },
        get _calls() {
            return checkValidityCalls;
        },
    };
    return child;
}

describe("checkValidity — scoped removeInvalidOnly (x2many children)", () => {
    test("(4c) committing a child row does not re-validate a valid dirty sibling", () => {
        // Valid sibling FIRST so it is visited before .every() short-circuits on
        // the invalid row — proving the skip comes from the valid-row shortcut,
        // not from short-circuit evaluation.
        const validSibling = makeChildRecord({ valid: true });
        const editedRow = makeChildRecord({ valid: false });
        const list = { records: [validSibling, editedRow], count: 2 };
        const rec = makeOrchestrationRecord({
            activeFields: { line_ids: {} },
            fields: { line_ids: { type: "one2many" } },
            data: { line_ids: list },
            // list is flagged because a child is invalid
            unsetRequired: ["line_ids"],
            invalid: ["line_ids"],
        });
        const scopedFields = computeRevalidationScope(["line_ids"], rec.activeFields);
        checkValidity(rec, { removeInvalidOnly: true, scopedFields });
        // valid sibling skipped (shortcut); the invalid edited row re-checked.
        expect(validSibling._calls).toBe(0);
        expect(editedRow._calls).toBe(1);
    });

    test("(4c) save-time full validation re-validates every dirty child row", () => {
        // Two valid dirty rows: .every() visits both (no short-circuit), and
        // default mode has NO valid-row shortcut, so both are re-validated.
        const row1 = makeChildRecord({ valid: true });
        const row2 = makeChildRecord({ valid: true });
        const list = { records: [row1, row2], count: 2 };
        const rec = makeOrchestrationRecord({
            activeFields: { line_ids: {} },
            fields: { line_ids: { type: "one2many" } },
            data: { line_ids: list },
        });
        // Default (save-time) validation: no removeInvalidOnly, no scope.
        checkValidity(rec, { displayNotification: true });
        expect(row1._calls).toBe(1);
        expect(row2._calls).toBe(1);
    });

    test("removeInvalidOnly DOES apply the valid-row shortcut (contrast to default)", () => {
        const row1 = makeChildRecord({ valid: true });
        const row2 = makeChildRecord({ valid: true });
        const list = { records: [row1, row2], count: 2 };
        const rec = makeOrchestrationRecord({
            activeFields: { line_ids: {} },
            fields: { line_ids: { type: "one2many" } },
            data: { line_ids: list },
            unsetRequired: ["line_ids"],
            invalid: ["line_ids"],
        });
        const scopedFields = computeRevalidationScope(["line_ids"], rec.activeFields);
        checkValidity(rec, { removeInvalidOnly: true, scopedFields });
        // Both rows valid -> both skipped by the shortcut.
        expect(row1._calls).toBe(0);
        expect(row2._calls).toBe(0);
    });

    test("silent mode re-validates every dirty child row (no valid-row shortcut)", () => {
        const row1 = makeChildRecord({ valid: true });
        const row2 = makeChildRecord({ valid: true });
        const list = { records: [row1, row2], count: 2 };
        const rec = makeOrchestrationRecord({
            activeFields: { line_ids: {} },
            fields: { line_ids: { type: "one2many" } },
            data: { line_ids: list },
        });
        checkValidity(rec, { silent: true });
        expect(row1._calls).toBe(1);
        expect(row2._calls).toBe(1);
    });
});
