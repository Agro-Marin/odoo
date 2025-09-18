// @ts-check

/**
 * Pure unit tests for commands.js.
 *
 * Tests x2ManyCommands constants and factory functions without OWL or DOM.
 */

import { describe, expect, test } from "@odoo/hoot";
import { x2ManyCommands } from "@web/model/relational_model/commands";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

describe("x2ManyCommands constants", () => {
    test("has correct numeric values", () => {
        expect(x2ManyCommands.CREATE).toBe(0);
        expect(x2ManyCommands.UPDATE).toBe(1);
        expect(x2ManyCommands.DELETE).toBe(2);
        expect(x2ManyCommands.UNLINK).toBe(3);
        expect(x2ManyCommands.LINK).toBe(4);
        expect(x2ManyCommands.CLEAR).toBe(5);
        expect(x2ManyCommands.SET).toBe(6);
    });
});

// ---------------------------------------------------------------------------
// Factory functions
// ---------------------------------------------------------------------------

describe("x2ManyCommands.create", () => {
    test("returns [CREATE, virtualId, values]", () => {
        const result = x2ManyCommands.create("virtual_1", { name: "New" });
        expect(result[0]).toBe(0);
        expect(result[1]).toBe("virtual_1");
        expect(result[2]).toEqual({ name: "New" });
    });

    test("deletes id from values", () => {
        const result = x2ManyCommands.create("v1", { id: 5, name: "Test" });
        expect("id" in result[2]).toBe(false);
        expect(result[2].name).toBe("Test");
    });

    test("uses false when virtualId is falsy", () => {
        const result = x2ManyCommands.create(null, { name: "X" });
        expect(result[1]).toBe(false);
    });
});

describe("x2ManyCommands.update", () => {
    test("returns [UPDATE, id, values]", () => {
        const result = x2ManyCommands.update(7, { name: "Updated" });
        expect(result[0]).toBe(1);
        expect(result[1]).toBe(7);
        expect(result[2]).toEqual({ name: "Updated" });
    });

    test("deletes id from values", () => {
        const result = x2ManyCommands.update(3, { id: 3, status: "done" });
        expect("id" in result[2]).toBe(false);
        expect(result[2].status).toBe("done");
    });
});

describe("x2ManyCommands.delete", () => {
    test("returns [DELETE, id, false]", () => {
        expect(x2ManyCommands.delete(5)).toEqual([2, 5, false]);
    });
});

describe("x2ManyCommands.unlink", () => {
    test("returns [UNLINK, id, false]", () => {
        expect(x2ManyCommands.unlink(9)).toEqual([3, 9, false]);
    });
});

describe("x2ManyCommands.link", () => {
    test("returns [LINK, id, false]", () => {
        expect(x2ManyCommands.link(3)).toEqual([4, 3, false]);
    });
});

describe("x2ManyCommands.clear", () => {
    test("returns [CLEAR, false, false]", () => {
        expect(x2ManyCommands.clear()).toEqual([5, false, false]);
    });
});

describe("x2ManyCommands.set", () => {
    test("returns [SET, false, ids]", () => {
        expect(x2ManyCommands.set([1, 2, 3])).toEqual([6, false, [1, 2, 3]]);
    });

    test("handles empty ids list", () => {
        expect(x2ManyCommands.set([])).toEqual([6, false, []]);
    });
});
