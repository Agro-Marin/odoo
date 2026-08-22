// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { Domain } from "@web/core/domain";
import { condition } from "@web/core/tree/condition_tree";
import { constructDomainFromTree } from "@web/core/tree/construct_domain_from_tree";
import { eliminateVirtualOperators } from "@web/core/tree/virtual_operators";

describe.current.tags("headless");

/**
 * @param {any} path
 * @param {string} operator
 * @param {any} value
 */
function eliminate(path, operator, value) {
    return constructDomainFromTree(
        eliminateVirtualOperators(condition(path, operator, value)),
    );
}

describe("eliminating a virtual operator keeps the path", () => {
    test("a plain path stays put", () => {
        expect(eliminate("amount", "between", [1, 5])).toBe(
            `["&", ("amount", ">=", 1), ("amount", "<=", 5)]`,
        );
    });

    test("a dotted path is split into an `any` subdomain", () => {
        expect(eliminate("line_ids.amount", "between", [1, 5])).toBe(
            `[("line_ids", "any", ["&", ("amount", ">=", 1), ("amount", "<=", 5)])]`,
        );
    });

    test("a non-string path survives", () => {
        expect(eliminate(1, "between", [1, 5])).toBe(
            `["&", (1, ">=", 1), (1, "<=", 5)]`,
        );
        expect(
            eliminate(1, "in range", [
                "date",
                "custom range",
                "2020-01-01",
                "2020-02-01",
            ]),
        ).toBe(`["&", (1, ">=", "2020-01-01"), (1, "<=", "2020-02-01")]`);
    });
});

describe("Domain.contains covers every operator the server defines", () => {
    test("the internal `any!` spellings are handled like `any`", () => {
        expect(new Domain([["id", "any!", [1]]]).contains({ id: 1 })).toBe(true);
        expect(new Domain([["id", "not any!", [1]]]).contains({ id: 1 })).toBe(false);
        expect(new Domain([["id", "any", [1]]]).contains({ id: 1 })).toBe(true);
        expect(new Domain([["id", "not any", [1]]]).contains({ id: 1 })).toBe(false);
    });

    test("an operator the server does not define is still refused", () => {
        expect(() => new Domain([["id", "wat", 1]]).contains({ id: 1 })).toThrow(
            /could not match domain/,
        );
    });
});

describe("Domain singletons are immutable", () => {
    test("TRUE and FALSE cannot be edited out from under their readers", () => {
        expect(Object.isFrozen(Domain.TRUE)).toBe(true);
        expect(Object.isFrozen(Domain.TRUE.ast.value)).toBe(true);
        expect(() => Domain.TRUE.ast.value.push(/** @type {any} */ ({}))).toThrow();
        expect(Domain.TRUE.toString()).toBe(`[(1, "=", 1)]`);
        expect(Domain.FALSE.toString()).toBe(`[(0, "=", 1)]`);
    });
});
