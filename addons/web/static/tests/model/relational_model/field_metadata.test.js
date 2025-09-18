// @ts-check

/**
 * Pure unit tests for field_metadata.js.
 *
 * Tests makeActiveField, combineModifiers, patchActiveFields,
 * createPropertyActiveField, and addFieldDependencies
 * without OWL, DOM, or a mock server.
 */

import { describe, expect, test } from "@odoo/hoot";
import {
    addFieldDependencies,
    combineModifiers,
    createPropertyActiveField,
    makeActiveField,
    patchActiveFields,
} from "@web/model/relational_model/field_metadata";

// ---------------------------------------------------------------------------
// makeActiveField
// ---------------------------------------------------------------------------

describe("makeActiveField — defaults", () => {
    test("no args produces default field", () => {
        const f = makeActiveField();
        expect(f.context).toBe("{}");
        expect(f.invisible).toBe("False");
        expect(f.readonly).toBe("False");
        expect(f.required).toBe("False");
        expect(f.onChange).toBe(false);
        expect(f.forceSave).toBe(false);
        expect(f.isHandle).toBe(false);
    });
});

describe("makeActiveField — boolean conversions", () => {
    test("boolean true → 'True' for invisible", () => {
        expect(makeActiveField({ invisible: true }).invisible).toBe("True");
    });

    test("boolean false → 'False' for readonly", () => {
        expect(makeActiveField({ readonly: false }).readonly).toBe("False");
    });

    test("boolean true → 'True' for required", () => {
        expect(makeActiveField({ required: true }).required).toBe("True");
    });

    test("string expression passed through unchanged", () => {
        const f = makeActiveField({
            invisible: "state == 'done'",
            readonly: "amount > 0",
        });
        expect(f.invisible).toBe("state == 'done'");
        expect(f.readonly).toBe("amount > 0");
    });
});

describe("makeActiveField — optional fields", () => {
    test("context is set when provided", () => {
        expect(makeActiveField({ context: "{'a': 1}" }).context).toBe("{'a': 1}");
    });

    test("onChange, forceSave, isHandle set correctly", () => {
        const f = makeActiveField({ onChange: true, forceSave: true, isHandle: true });
        expect(f.onChange).toBe(true);
        expect(f.forceSave).toBe(true);
        expect(f.isHandle).toBe(true);
    });
});

// ---------------------------------------------------------------------------
// combineModifiers
// ---------------------------------------------------------------------------

describe("combineModifiers — AND", () => {
    test("False AND anything = False", () => {
        expect(combineModifiers("False", "True", "AND")).toBe("False");
        expect(combineModifiers("False", "expr", "AND")).toBe("False");
        expect(combineModifiers("True", "False", "AND")).toBe("False");
    });

    test("falsy mod1 AND anything = False", () => {
        expect(combineModifiers(false, "True", "AND")).toBe("False");
        expect(combineModifiers("", "expr", "AND")).toBe("False");
    });

    test("True AND expr = expr", () => {
        expect(combineModifiers("True", "state == 'done'", "AND")).toBe("state == 'done'");
    });

    test("expr AND True = expr", () => {
        expect(combineModifiers("state == 'done'", "True", "AND")).toBe("state == 'done'");
    });

    test("two expressions joined with AND", () => {
        const result = combineModifiers("a > 0", "b == 'done'", "AND");
        expect(result).toBe("(a > 0) and (b == 'done')");
    });
});

describe("combineModifiers — OR", () => {
    test("True OR anything = True", () => {
        expect(combineModifiers("True", "False", "OR")).toBe("True");
        expect(combineModifiers("False", "True", "OR")).toBe("True");
    });

    test("False OR expr = expr", () => {
        expect(combineModifiers("False", "state == 'done'", "OR")).toBe("state == 'done'");
    });

    test("falsy OR expr = expr", () => {
        expect(combineModifiers(false, "x > 0", "OR")).toBe("x > 0");
    });

    test("expr OR False = expr", () => {
        expect(combineModifiers("x > 0", "False", "OR")).toBe("x > 0");
    });

    test("two expressions joined with OR", () => {
        const result = combineModifiers("a > 0", "b == 'done'", "OR");
        expect(result).toBe("(a > 0) or (b == 'done')");
    });
});

describe("combineModifiers — invalid operator", () => {
    test("throws for unknown operator", () => {
        expect(() => combineModifiers("True", "False", "XOR")).toThrow(Error);
    });
});

// ---------------------------------------------------------------------------
// patchActiveFields
// ---------------------------------------------------------------------------

describe("patchActiveFields", () => {
    test("invisible combines with AND", () => {
        const base = makeActiveField({ invisible: "state == 'done'" });
        const patch = makeActiveField({ invisible: "amount > 0" });
        patchActiveFields(base, patch);
        expect(base.invisible).toBe("(state == 'done') and (amount > 0)");
    });

    test("readonly combines with AND", () => {
        const base = makeActiveField({ readonly: "True" });
        const patch = makeActiveField({ readonly: "False" });
        patchActiveFields(base, patch);
        // True AND False = False
        expect(base.readonly).toBe("False");
    });

    test("required combines with OR", () => {
        const base = makeActiveField({ required: "False" });
        const patch = makeActiveField({ required: "state == 'done'" });
        patchActiveFields(base, patch);
        expect(base.required).toBe("state == 'done'");
    });

    test("onChange is set to true when patch has it", () => {
        const base = makeActiveField({ onChange: false });
        const patch = makeActiveField({ onChange: true });
        patchActiveFields(base, patch);
        expect(base.onChange).toBe(true);
    });

    test("forceSave is set to true when patch has it", () => {
        const base = makeActiveField();
        const patch = makeActiveField({ forceSave: true });
        patchActiveFields(base, patch);
        expect(base.forceSave).toBe(true);
    });

    test("isHandle is set to true when patch has it", () => {
        const base = makeActiveField();
        const patch = makeActiveField({ isHandle: true });
        patchActiveFields(base, patch);
        expect(base.isHandle).toBe(true);
    });

    test("limit set from patch", () => {
        const base = makeActiveField();
        const patch = { ...makeActiveField(), limit: 20 };
        patchActiveFields(base, patch);
        expect(base.limit).toBe(20);
    });

    test("defaultOrderBy set from patch", () => {
        const base = makeActiveField();
        const patch = { ...makeActiveField(), defaultOrderBy: [{ name: "name", asc: true }] };
        patchActiveFields(base, patch);
        expect(base.defaultOrderBy).toEqual([{ name: "name", asc: true }]);
    });
});

// ---------------------------------------------------------------------------
// createPropertyActiveField
// ---------------------------------------------------------------------------

describe("createPropertyActiveField", () => {
    test("creates basic active field for simple types", () => {
        const f = createPropertyActiveField({ type: "char" });
        expect(f.invisible).toBe("False");
        expect(f.readonly).toBe("False");
        expect("related" in f).toBe(false);
    });

    test("creates field with related for one2many", () => {
        const f = createPropertyActiveField({ type: "one2many" });
        expect("related" in f).toBe(true);
        expect(f.related.fields.id.type).toBe("integer");
        expect(f.related.fields.display_name.type).toBe("char");
        expect(f.related.activeFields.id.readonly).toBe("True");
    });

    test("creates field with related for many2many", () => {
        const f = createPropertyActiveField({ type: "many2many" });
        expect("related" in f).toBe(true);
    });
});

// ---------------------------------------------------------------------------
// addFieldDependencies
// ---------------------------------------------------------------------------

describe("addFieldDependencies", () => {
    test("adds new field to activeFields and fields", () => {
        const activeFields = {};
        const fields = {};
        addFieldDependencies(activeFields, fields, [
            { name: "currency_id", type: "many2one" },
        ]);
        expect("currency_id" in activeFields).toBe(true);
        expect("currency_id" in fields).toBe(true);
        expect(fields.currency_id.type).toBe("many2one");
    });

    test("default readonly=true for new dependency", () => {
        const activeFields = {};
        const fields = {};
        addFieldDependencies(activeFields, fields, [
            { name: "company_id", type: "many2one" },
        ]);
        expect(activeFields.company_id.readonly).toBe("True");
    });

    test("patches existing active field (doesn't duplicate)", () => {
        const activeFields = { name: makeActiveField({ readonly: false }) };
        const fields = { name: { type: "char" } };
        addFieldDependencies(activeFields, fields, [
            { name: "name", type: "char", readonly: false },
        ]);
        // Should still have exactly one entry
        expect(Object.keys(activeFields).length).toBe(1);
    });

    test("x2many dependency gets related structure", () => {
        const activeFields = {};
        const fields = {};
        addFieldDependencies(activeFields, fields, [
            { name: "line_ids", type: "one2many" },
        ]);
        expect(activeFields.line_ids.related).toBeOfType("object");
        expect(activeFields.line_ids.related.activeFields).toEqual({});
        expect(activeFields.line_ids.related.fields).toEqual({});
    });

    test("no-op when fieldDependencies is empty", () => {
        const activeFields = {};
        const fields = {};
        addFieldDependencies(activeFields, fields, []);
        expect(Object.keys(activeFields).length).toBe(0);
    });
});
