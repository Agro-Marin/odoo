// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { evaluateExpr } from "@web/core/py_js/py";
import { Registry, registry } from "@web/core/registry";

describe.current.tags("headless");

/**
 * Every member of ``Object.prototype`` is a truthy answer to ``key in {}``.
 * Where a name comes from data -- a registry category, a context key, a field
 * name -- the containers below must answer for their *own* keys only.
 */
const INHERITED_KEYS = [
    "constructor",
    "toString",
    "valueOf",
    "hasOwnProperty",
    "isPrototypeOf",
    "propertyIsEnumerable",
    "toLocaleString",
    "__proto__",
];

describe("Registry", () => {
    test("category() creates a Registry for a name Object.prototype also carries", () => {
        // `subcategory in this.subRegistries` was true for all of these, so
        // `category("constructor")` handed back the Object constructor and the
        // caller's next `.add()` was a TypeError far from the cause.
        const root = new Registry("root");
        for (const key of INHERITED_KEYS) {
            const sub = root.category(/** @type {any} */ (key));
            expect(sub).toBeInstanceOf(Registry);
            expect(sub.add(`${key}-entry`, 1).get(`${key}-entry`)).toBe(1);
        }
    });

    test("the global registry behaves the same", () => {
        const sub = registry.category(/** @type {any} */ ("toString"));
        expect(sub).toBeInstanceOf(Registry);
    });

    test("distinct names still get distinct sub-registries", () => {
        const root = new Registry("root");
        expect(root.category(/** @type {any} */ ("a"))).not.toBe(
            root.category(/** @type {any} */ ("b")),
        );
        expect(root.category(/** @type {any} */ ("a"))).toBe(
            root.category(/** @type {any} */ ("a")),
        );
    });
});

describe("py_js name resolution", () => {
    test("an inherited name is not a defined name", () => {
        for (const key of INHERITED_KEYS) {
            expect(() => evaluateExpr(key)).toThrow(
                new RegExp(`'${key}' is not defined`),
            );
        }
    });

    test("a context key shadowing an inherited name still resolves", () => {
        expect(evaluateExpr("toString", { toString: 5 })).toBe(5);
    });
});
