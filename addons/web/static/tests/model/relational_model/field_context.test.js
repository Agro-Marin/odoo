// @ts-check

/**
 * Pure unit tests for field_context.js.
 *
 * Tests getId, isRelational, and getBasicEvalContext without OWL or DOM.
 * getFieldContext and getFieldDomain are not tested here — they require
 * a full Record instance with evalContext (covered by integration tests).
 */

import { describe, expect, test } from "@odoo/hoot";
import {
    getBasicEvalContext,
    getId,
    isRelational,
} from "@web/model/relational_model/field_context";

// ---------------------------------------------------------------------------
// getId
// ---------------------------------------------------------------------------

describe("getId", () => {
    test("returns unique string IDs on successive calls", () => {
        const id1 = getId();
        const id2 = getId();
        expect(id1).not.toBe(id2);
    });

    test("includes prefix when provided", () => {
        const id = getId("virtual");
        expect(id.startsWith("virtual_")).toBe(true);
    });

    test("uses empty prefix when not provided", () => {
        const id = getId();
        expect(id.startsWith("_")).toBe(true);
    });

    test("each call increments the ID", () => {
        const before = getId("x");
        const after = getId("x");
        const numBefore = parseInt(before.split("_")[1], 10);
        const numAfter = parseInt(after.split("_")[1], 10);
        expect(numAfter).toBe(numBefore + 1);
    });
});

// ---------------------------------------------------------------------------
// isRelational
// ---------------------------------------------------------------------------

describe("isRelational", () => {
    test("returns true for many2one", () => {
        expect(isRelational({ type: "many2one" })).toBe(true);
    });

    test("returns true for one2many", () => {
        expect(isRelational({ type: "one2many" })).toBe(true);
    });

    test("returns true for many2many", () => {
        expect(isRelational({ type: "many2many" })).toBe(true);
    });

    test("returns false for char", () => {
        expect(isRelational({ type: "char" })).toBe(false);
    });

    test("returns false for float", () => {
        expect(isRelational({ type: "float" })).toBe(false);
    });

    test("returns null/undefined for null/undefined field", () => {
        expect(isRelational(null)).toBe(null);
        expect(isRelational(undefined)).toBe(undefined);
    });
});

// ---------------------------------------------------------------------------
// getBasicEvalContext
// ---------------------------------------------------------------------------

describe("getBasicEvalContext", () => {
    test("extracts uid and allowed_company_ids from config context", () => {
        const config = {
            context: { uid: 3, allowed_company_ids: [1, 2] },
        };
        const result = getBasicEvalContext(config);
        expect(result.uid).toBe(3);
        expect(result.allowed_company_ids).toEqual([1, 2]);
    });

    test("sets current_company_id to first of allowed_company_ids", () => {
        const config = {
            context: { uid: 1, allowed_company_ids: [5, 7] },
        };
        expect(getBasicEvalContext(config).current_company_id).toBe(5);
    });

    test("current_company_id is undefined when allowed_company_ids absent", () => {
        const config = { context: { uid: 1 } };
        const result = getBasicEvalContext(config);
        expect(result.current_company_id).toBe(undefined);
    });

    test("passes context reference through", () => {
        const ctx = { uid: 2, allowed_company_ids: [] };
        const config = { context: ctx };
        expect(getBasicEvalContext(config).context).toBe(ctx);
    });
});
