// @ts-check

/**
 * Pure unit tests for record_preprocessors.js.
 *
 * All exported functions accept a RelationalRecord-shaped plain object —
 * no OWL component, no DOM, no mock server.
 *
 * The only OWL import is markup() from @odoo/owl, available in the Hoot
 * browser environment without mounting a component.
 *
 * Module under test: model/relational_model/record_preprocessors.js
 */

import { describe, expect, test } from "@odoo/hoot";
import { markup } from "@odoo/owl";
import {
    completeMany2OneValue,
    preprocessHtmlChanges,
    preprocessMany2OneReferenceChanges,
    preprocessMany2oneChanges,
    preprocessPropertiesChanges,
    preprocessReferenceChanges,
    preprocessX2manyChanges,
} from "@web/model/relational_model/record_preprocessors";
import { x2ManyCommands } from "@web/model/relational_model/commands";

// ---------------------------------------------------------------------------
// Mock factory
// ---------------------------------------------------------------------------

/**
 * Builds a minimal record mock. Only includes the properties each tested
 * code path actually accesses — unused paths are left absent.
 *
 * @param {Object} [opts]
 * @param {Object} [opts.fields]
 * @param {Object} [opts.activeFields]
 * @param {Object} [opts.data]
 * @param {Function} [opts.ormCall]
 * @param {Function} [opts.ormWebRead]
 * @param {Function} [opts.processProperties]
 * @param {Function} [opts.onDisplayPropertyWarning]
 * @returns {Object}
 */
function makeRecord({
    fields = {},
    activeFields = {},
    data = {},
    ormCall = async () => null,
    ormWebRead = async () => [],
    processProperties = () => ({}),
    onDisplayPropertyWarning = () => {},
} = {}) {
    return {
        context: {},
        evalContext: {},
        config: { context: { uid: 1, allowed_company_ids: [1] } },
        fields,
        activeFields,
        data,
        model: {
            orm: { call: ormCall, webRead: ormWebRead },
            hooks: { onDisplayPropertyWarning },
        },
        _processProperties: processProperties,
    };
}

// ---------------------------------------------------------------------------
// completeMany2OneValue — 4 branches
// ---------------------------------------------------------------------------

describe("completeMany2OneValue", () => {
    test("returns false when value has no id and no display_name", async () => {
        const rec = makeRecord({
            fields: { partner_id: { type: "many2one", context: {} } },
            activeFields: { partner_id: { context: "{}" } },
        });
        // {} → resId=undefined (falsy), displayName=undefined (falsy)
        const result = await completeMany2OneValue(rec, {}, "partner_id", "res.partner");
        expect(result).toBe(false);
    });

    test("calls name_create when display_name is present but id is absent", async () => {
        let nameCreateArgs = null;
        const rec = makeRecord({
            fields: { partner_id: { type: "many2one", context: {} } },
            activeFields: { partner_id: { context: "{}", related: null } },
            ormCall: async (model, method, args) => {
                nameCreateArgs = { model, method, args };
                return [42, "Acme Corp"];
            },
        });
        const result = await completeMany2OneValue(
            rec,
            { display_name: "Acme Corp" },
            "partner_id",
            "res.partner",
        );
        expect(nameCreateArgs.method).toBe("name_create");
        expect(nameCreateArgs.args).toEqual(["Acme Corp"]);
        expect(result).toEqual({ id: 42, display_name: "Acme Corp" });
    });

    test("calls webRead when id is present but display_name is undefined", async () => {
        let webReadArgs = null;
        const rec = makeRecord({
            fields: { partner_id: { type: "many2one", context: {} } },
            activeFields: { partner_id: { context: "{}", related: null } },
            ormWebRead: async (model, ids) => {
                webReadArgs = { model, ids };
                return [{ id: 42, display_name: "Acme Corp" }];
            },
        });
        const result = await completeMany2OneValue(
            rec,
            { id: 42 },
            "partner_id",
            "res.partner",
        );
        expect(webReadArgs.ids).toEqual([42]);
        expect(result).toEqual({ id: 42, display_name: "Acme Corp" });
    });

    test("returns value as-is when both id and display_name are provided", async () => {
        const rec = makeRecord({
            fields: { partner_id: { type: "many2one", context: {} } },
            activeFields: { partner_id: { context: "{}" } },
        });
        const value = { id: 42, display_name: "Acme Corp" };
        const result = await completeMany2OneValue(rec, value, "partner_id", "res.partner");
        // Both present — no RPC needed, value returned as-is
        expect(result).toBe(value);
    });
});

// ---------------------------------------------------------------------------
// preprocessMany2oneChanges — falsy value, missing activeField, normal path
// ---------------------------------------------------------------------------

describe("preprocessMany2oneChanges", () => {
    test("sets falsy many2one change to false", async () => {
        const rec = makeRecord({
            fields: { partner_id: { type: "many2one", context: {} } },
            activeFields: { partner_id: { context: "{}" } },
        });
        const changes = { partner_id: 0 };
        await preprocessMany2oneChanges(rec, changes);
        expect(changes.partner_id).toBe(false);
    });

    test("keeps value unchanged when field is not in activeFields", async () => {
        const rec = makeRecord({
            fields: { partner_id: { type: "many2one", context: {} } },
            activeFields: {}, // partner_id absent from activeFields
        });
        const original = { id: 1, display_name: "kept" };
        const changes = { partner_id: original };
        await preprocessMany2oneChanges(rec, changes);
        // !record.activeFields["partner_id"] → keeps value unchanged
        expect(changes.partner_id).toBe(original);
    });

    test("completes value when field is in activeFields with both id and display_name", async () => {
        const rec = makeRecord({
            fields: { partner_id: { type: "many2one", relation: "res.partner", context: {} } },
            activeFields: { partner_id: { context: "{}", related: null } },
        });
        const changes = { partner_id: { id: 5, display_name: "Acme" } };
        await preprocessMany2oneChanges(rec, changes);
        // Both present → completeMany2OneValue returns value unchanged
        expect(changes.partner_id).toEqual({ id: 5, display_name: "Acme" });
    });
});

// ---------------------------------------------------------------------------
// preprocessMany2OneReferenceChanges — falsy and integer branches
// ---------------------------------------------------------------------------

describe("preprocessMany2OneReferenceChanges", () => {
    test("sets falsy many2one_reference change to false", async () => {
        const rec = makeRecord({
            fields: { ref_id: { type: "many2one_reference", context: {} } },
            activeFields: { ref_id: { context: "{}" } },
        });
        const changes = { ref_id: null };
        await preprocessMany2OneReferenceChanges(rec, changes);
        expect(changes.ref_id).toBe(false);
    });

    test("wraps a numeric id into { resId } without an RPC call", async () => {
        let ormCalled = false;
        const rec = makeRecord({
            fields: { ref_id: { type: "many2one_reference", context: {} } },
            activeFields: {},
            ormCall: async () => {
                ormCalled = true;
                return null;
            },
        });
        const changes = { ref_id: 42 };
        await preprocessMany2OneReferenceChanges(rec, changes);
        // Numeric id path: sets { resId: value } without calling orm
        expect(changes.ref_id).toEqual({ resId: 42 });
        expect(ormCalled).toBe(false);
    });
});

// ---------------------------------------------------------------------------
// preprocessReferenceChanges — falsy and object branches
// ---------------------------------------------------------------------------

describe("preprocessReferenceChanges", () => {
    test("sets falsy reference change to false", async () => {
        const rec = makeRecord({
            fields: { ref_field: { type: "reference", context: {} } },
            activeFields: { ref_field: { context: "{}" } },
        });
        const changes = { ref_field: false };
        await preprocessReferenceChanges(rec, changes);
        expect(changes.ref_field).toBe(false);
    });

    test("normalises a reference object when both resId and displayName are provided", async () => {
        const rec = makeRecord({
            fields: { ref_field: { type: "reference", context: {} } },
            activeFields: { ref_field: { context: "{}", related: null } },
        });
        // When both id and display_name are present, completeMany2OneValue returns the
        // value unchanged — no ORM calls needed.
        const changes = {
            ref_field: { resId: 5, displayName: "Acme", resModel: "res.partner" },
        };
        await preprocessReferenceChanges(rec, changes);
        expect(changes.ref_field).toEqual({
            resId: 5,
            resModel: "res.partner",
            displayName: "Acme",
        });
    });
});

// ---------------------------------------------------------------------------
// preprocessX2manyChanges — SET command vs other commands
// ---------------------------------------------------------------------------

describe("preprocessX2manyChanges", () => {
    test("SET command calls list._replaceWith with the new ids array", async () => {
        let replacedWith = null;
        const list = {
            _replaceWith: async (ids) => {
                replacedWith = ids;
            },
            _applyCommands: async () => {},
        };
        const rec = makeRecord({
            fields: { turtles: { type: "one2many" } },
            data: { turtles: list },
        });
        const changes = { turtles: [x2ManyCommands.set([1, 2, 3])] };
        await preprocessX2manyChanges(rec, changes);
        expect(replacedWith).toEqual([1, 2, 3]);
        // After processing, changes[fieldName] is replaced with the list object
        expect(changes.turtles).toBe(list);
    });

    test("non-SET command calls list._applyCommands with a single-element array", async () => {
        let appliedCommands = null;
        const list = {
            _replaceWith: async () => {},
            _applyCommands: async (cmds) => {
                appliedCommands = cmds;
            },
        };
        const deleteCmd = x2ManyCommands.delete(7);
        const rec = makeRecord({
            fields: { turtles: { type: "one2many" } },
            data: { turtles: list },
        });
        const changes = { turtles: [deleteCmd] };
        await preprocessX2manyChanges(rec, changes);
        // Each non-SET command is dispatched individually
        expect(appliedCommands).toEqual([deleteCmd]);
        expect(changes.turtles).toBe(list);
    });
});

// ---------------------------------------------------------------------------
// preprocessPropertiesChanges — properties type and relatedPropertyField
// ---------------------------------------------------------------------------

describe("preprocessPropertiesChanges", () => {
    test("properties field calls _processProperties and merges result into changes", () => {
        const rec = makeRecord({
            fields: {
                my_props: { type: "properties", definition_record: "project_id" },
            },
            data: { project_id: { id: 1 } },
            processProperties: () => ({ extra_key: "computed" }),
        });
        const changes = { my_props: [{ name: "color", value: "red" }] };
        preprocessPropertiesChanges(rec, changes);
        // _processProperties result is merged into changes
        expect(changes.extra_key).toBe("computed");
    });

    test("relatedPropertyField maps updated value into the parent properties array", () => {
        const rec = makeRecord({
            fields: {
                "my_props.color": {
                    type: "char",
                    relatedPropertyField: true,
                    name: "my_props.color",
                },
            },
            data: {
                my_props: [{ name: "color", value: "red" }],
            },
        });
        const changes = { "my_props.color": "blue" };
        preprocessPropertiesChanges(rec, changes);
        // The matching property entry is updated in-place; others are left unchanged
        expect(changes.my_props).toEqual([{ name: "color", value: "blue" }]);
    });

    test("relatedPropertyField calls onDisplayPropertyWarning when property not found", () => {
        let warned = false;
        const rec = makeRecord({
            fields: {
                "other.color": {
                    type: "char",
                    relatedPropertyField: true,
                    name: "other.color",
                },
            },
            data: {
                // "other" array contains a different property name
                other: [{ name: "size", value: "large" }],
            },
            onDisplayPropertyWarning: () => {
                warned = true;
            },
        });
        const changes = { "other.color": "blue" };
        preprocessPropertiesChanges(rec, changes);
        expect(warned).toBe(true);
        // changes should not have been mutated (function returns early)
        expect(changes["other"]).toBe(undefined);
    });
});

// ---------------------------------------------------------------------------
// preprocessHtmlChanges — markup wrapping vs false passthrough
// ---------------------------------------------------------------------------

describe("preprocessHtmlChanges", () => {
    test("wraps html field string value with markup()", () => {
        const rec = makeRecord({
            fields: { description: { type: "html" } },
        });
        const changes = { description: "<p>hello</p>" };
        preprocessHtmlChanges(rec, changes);
        // Content must be preserved
        expect(String(changes.description)).toBe("<p>hello</p>");
        // Must not remain a plain string (markup() wraps it in a Markup object)
        expect(changes.description).not.toBe("<p>hello</p>");
        // Should match what markup() produces for the same input
        expect(changes.description).toEqual(markup("<p>hello</p>"));
    });

    test("passes false through without wrapping for html field", () => {
        const rec = makeRecord({
            fields: { description: { type: "html" } },
        });
        const changes = { description: false };
        preprocessHtmlChanges(rec, changes);
        expect(changes.description).toBe(false);
    });
});
