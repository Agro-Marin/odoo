// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { patchWithCleanup } from "@web/../tests/web_test_helpers";
import { applyFieldDirtyPayload } from "@web/fields/field_dirty_signal";

describe.current.tags("headless");

describe("owned payloads", () => {
    test("a payload adds and removes its own owner", () => {
        const owners = new Set();
        const id = Symbol("field-a");

        applyFieldDirtyPayload(owners, { id, isDirty: true });
        expect(owners.size).toBe(1);

        applyFieldDirtyPayload(owners, { id, isDirty: false });
        expect(owners.size).toBe(0);
    });

    test("one owner going clean does not clear another's mark", () => {
        const owners = new Set();
        const a = Symbol("field-a");
        const b = Symbol("field-b");

        applyFieldDirtyPayload(owners, { id: a, isDirty: true });
        applyFieldDirtyPayload(owners, { id: b, isDirty: true });
        applyFieldDirtyPayload(owners, { id: b, isDirty: false });

        expect(owners.size).toBe(1);
        expect(owners.has(a)).toBe(true);
    });
});

describe("legacy raw-boolean details", () => {
    test("a raw boolean detail throws in debug mode", () => {
        patchWithCleanup(/** @type {any} */ (globalThis).odoo, { debug: "1" });
        const owners = new Set();

        expect(() => applyFieldDirtyPayload(owners, true)).toThrow(
            /useFieldDirtySignal/,
        );
        expect(owners.size).toBe(0);
    });

    test("a raw boolean detail is warn-ignored outside debug mode", () => {
        patchWithCleanup(/** @type {any} */ (globalThis).odoo, { debug: "" });
        const owners = new Set();
        const id = Symbol("field-a");
        applyFieldDirtyPayload(owners, { id, isDirty: true });

        /** @type {any[]} */
        const warnings = [];
        const originalWarn = console.warn;
        console.warn = (...args) => warnings.push(args.join(" "));
        try {
            applyFieldDirtyPayload(owners, true);
            applyFieldDirtyPayload(owners, false);
        } finally {
            console.warn = originalWarn;
        }

        expect(warnings.length).toBe(2);
        expect(warnings[0]).toInclude("useFieldDirtySignal");
        expect(owners.size).toBe(1);
        expect(owners.has(id)).toBe(true);
    });
});
