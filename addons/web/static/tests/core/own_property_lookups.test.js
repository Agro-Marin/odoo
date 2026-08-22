// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { reactive } from "@odoo/owl";
import { evaluateExpr } from "@web/core/py_js/py";
import { Registry, registry } from "@web/core/registry";
import { pick } from "@web/core/utils/collections/objects";

describe.current.tags("headless");

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

describe("pick", () => {
    class PrototypeFieldRecord {
        constructor() {
            this.id = 7;
        }
    }
    Object.defineProperty(PrototypeFieldRecord.prototype, "position_h", {
        get() {
            return 42;
        },
        set() {},
        enumerable: true,
    });

    test("an inherited name is not a pickable key", () => {
        for (const key of INHERITED_KEYS) {
            expect(pick(/** @type {any} */ ({}), /** @type {any} */ (key))).toEqual({});
            expect(pick({ a: 1 }, /** @type {any} */ (key))).toEqual({});
        }
    });

    test("a key list from the server cannot smuggle a function into the values", () => {
        const rawValues = JSON.parse('{"id": 1, "name": "x"}');
        const fieldNames = ["id", "name", ...INHERITED_KEYS];
        const values = pick(rawValues, .../** @type {any} */ (fieldNames));
        expect(Object.keys(values)).toEqual(["id", "name"]);
        for (const value of Object.values(values)) {
            expect(typeof value).not.toBe("function");
        }
    });

    test("a field declared on the model class prototype is still picked", () => {
        expect(
            pick(new PrototypeFieldRecord(), /** @type {any} */ ("position_h")),
        ).toEqual({ position_h: 42 });
    });

    test("...including through OWL's reactive proxy, which POS records carry", () => {
        const record = reactive(new PrototypeFieldRecord());
        expect("position_h" in record).toBe(true);
        expect(Object.hasOwn(record, "position_h")).toBe(false);
        expect(
            pick(record, /** @type {any} */ ("position_h"), /** @type {any} */ ("id")),
        ).toEqual({ position_h: 42, id: 7 });
    });

    test("a null-prototype bag has no inherited keys to reach for", () => {
        const bag = Object.create(null);
        bag.a = 1;
        expect(
            pick(bag, /** @type {any} */ ("a"), /** @type {any} */ ("toString")),
        ).toEqual({
            a: 1,
        });
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
