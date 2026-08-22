// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import {
    computeSearchContext,
    computeSearchItemContext,
} from "@web/search/search_context";

describe.current.tags("headless");

/**
 * @param {Record<string, any>} searchItem
 * @param {Record<string, any>} [activeItem]
 */
function contextOf(searchItem, activeItem = {}) {
    return computeSearchItemContext(
        /** @type {any} */ ({ searchItemId: 1, ...activeItem }),
        /** @type {any} */ ({ 1: searchItem }),
    );
}

describe("computeSearchItemContext", () => {
    test("a field with no context contributes an empty one", () => {
        expect(contextOf({ type: "field" })).toEqual({});
    });

    test("a field's context sees the selected values as `self`", () => {
        const context = contextOf(
            { type: "field", context: "{'picked': self}" },
            { autocompleteValues: [{ value: 7 }, { value: 9 }] },
        );
        expect(context).toEqual({ picked: [7, 9] });
    });

    test("a default many2one field also seeds default_<fieldName>", () => {
        const context = contextOf({
            type: "field",
            fieldType: "many2one",
            fieldName: "partner_id",
            isDefault: true,
            defaultAutocompleteValue: { value: 42 },
        });
        expect(context).toEqual({ default_partner_id: 42 });
    });

    test("the default seed merges into an evaluated context", () => {
        const context = contextOf(
            {
                type: "field",
                fieldType: "many2one",
                fieldName: "partner_id",
                isDefault: true,
                defaultAutocompleteValue: { value: 42 },
                context: "{'from_arch': 1}",
            },
            { autocompleteValues: [] },
        );
        expect(context).toEqual({ from_arch: 1, default_partner_id: 42 });
    });

    test("a default field of another type does NOT seed a default", () => {
        const context = contextOf({
            type: "field",
            fieldType: "char",
            fieldName: "name",
            isDefault: true,
            defaultAutocompleteValue: { value: "abc" },
        });
        expect(context).toEqual({});
    });

    describe("a field context that is not a dict is refused", () => {
        for (const [label, expr] of [
            ["a string", "'nope'"],
            ["a number", "3"],
            ["None", "None"],
            ["a list", "[1, 2]"],
            ["a bool", "True"],
        ]) {
            test(label, () => {
                expect(() =>
                    contextOf(
                        { type: "field", context: expr },
                        { autocompleteValues: [] },
                    ),
                ).toThrow(/Failed to evaluate the context/);
            });
        }
    });

    test("a null context is refused even when a default would be seeded", () => {
        expect(() =>
            contextOf(
                {
                    type: "field",
                    fieldType: "many2one",
                    fieldName: "partner_id",
                    isDefault: true,
                    defaultAutocompleteValue: { value: 42 },
                    context: "None",
                },
                { autocompleteValues: [] },
            ),
        ).toThrow(/Failed to evaluate the context/);
    });

    for (const type of ["favorite", "filter"]) {
        test(`a ${type}'s context is copied, not aliased`, () => {
            const searchItem = { type, context: { nested: { a: 1 } } };
            const context = contextOf(searchItem);
            expect(context).toEqual({ nested: { a: 1 } });

            /** @type {any} */ (context).nested.a = 99;
            expect(searchItem.context).toEqual({ nested: { a: 1 } });
        });
    }

    test("a filter with no context contributes an empty one", () => {
        expect(contextOf({ type: "filter" })).toEqual({});
    });

    for (const type of ["dateFilter", "groupBy", "dateGroupBy", "field_property"]) {
        test(`a ${type} contributes no context at all`, () => {
            expect(contextOf({ type })).toBe(null);
        });
    }
});

describe("computeSearchContext", () => {
    test("the user context is the base, and active items layer over it", () => {
        const groups = [
            { activeItems: [{ searchItemId: 1 }, { searchItemId: 2 }] },
            { activeItems: [{ searchItemId: 3 }] },
        ];
        const contexts = {
            1: { a: 1 },
            2: { b: 2 },
            3: { a: 3 },
        };
        const result = computeSearchContext(
            /** @type {any} */ (groups),
            { lang: "en_US" },
            (/** @type {any} */ item) =>
                /** @type {Record<string, any>} */ (contexts)[item.searchItemId],
        );
        expect(result).toEqual({ lang: "en_US", a: 3, b: 2 });
    });

    test("items contributing null are skipped rather than merged", () => {
        const groups = [{ activeItems: [{ searchItemId: 1 }, { searchItemId: 2 }] }];
        const result = computeSearchContext(
            /** @type {any} */ (groups),
            { lang: "en_US" },
            (/** @type {any} */ item) => (item.searchItemId === 1 ? null : { b: 2 }),
        );
        expect(result).toEqual({ lang: "en_US", b: 2 });
    });

    test("no groups leaves the user context alone", () => {
        expect(computeSearchContext([], { lang: "en_US" }, () => ({}))).toEqual({
            lang: "en_US",
        });
    });
});
