import { expect, test } from "@odoo/hoot";
import {
    checkExclusions,
    findProduct,
    getChildProducts,
    getCombination,
    getParentsCombination,
    getVariantCombination,
    isPossibleCombination,
} from "@sale/js/product_configurator_dialog/product_configurator_utils";

function makeProduct(overrides = {}) {
    return {
        product_tmpl_id: 1,
        parent_product_tmpl_id: undefined,
        attribute_lines: [
            {
                id: 1,
                selected_attribute_value_ids: [11],
                attribute_values: [{ id: 11 }, { id: 12 }],
            },
            {
                id: 2,
                selected_attribute_value_ids: [21],
                attribute_values: [{ id: 21 }, { id: 22 }],
            },
        ],
        exclusions: {},
        parent_exclusions: {},
        archived_combinations: [],
        ...overrides,
    };
}

const valueById = (product, id) =>
    product.attribute_lines.flatMap((l) => l.attribute_values).find((v) => v.id === id);

test("getCombination collects selected ids across lines", () => {
    expect(getCombination(makeProduct())).toEqual([11, 21]);
});

test("findProduct / getChildProducts / getParentsCombination", () => {
    const parent = makeProduct({ product_tmpl_id: 1 });
    const child = makeProduct({
        product_tmpl_id: 2,
        parent_product_tmpl_id: 1,
        attribute_lines: [
            {
                id: 3,
                selected_attribute_value_ids: [31],
                attribute_values: [{ id: 31 }, { id: 32 }],
            },
        ],
    });
    const pool = [parent, child];
    expect(findProduct(pool, 2)).toBe(child);
    expect(findProduct(pool, 99)).toBe(undefined);
    expect(getChildProducts(pool, 1)).toEqual([child]);
    expect(getParentsCombination(pool, child)).toEqual([11, 21]);
    expect(getParentsCombination(pool, parent)).toEqual([]);
});

test("isPossibleCombination reflects excluded selected values", () => {
    expect(isPossibleCombination(makeProduct())).toBe(true);
    const bad = makeProduct();
    valueById(bad, 11).excluded = true;
    expect(isPossibleCombination(bad)).toBe(false);
});

test("checkExclusions: own exclusions mark the excluded value", () => {
    const p = makeProduct({ exclusions: { 11: [22], 12: [], 21: [], 22: [11] } });
    checkExclusions([p], p);
    expect(valueById(p, 22).excluded).toBe(true);
    expect(valueById(p, 12).excluded).toBe(false);
    expect(valueById(p, 11).excluded).toBe(false);
});

test("checkExclusions resets stale flags and tolerates sparse dicts", () => {
    const p = makeProduct({ exclusions: { 11: [22] } });
    valueById(p, 12).excluded = true;
    checkExclusions([p], p);
    expect(valueById(p, 12).excluded).toBe(false);
    expect(valueById(p, 22).excluded).toBe(true);
});

test("checkExclusions applies parent exclusions to children", () => {
    const parent = makeProduct({ product_tmpl_id: 1 });
    const child = makeProduct({
        product_tmpl_id: 2,
        parent_product_tmpl_id: 1,
        attribute_lines: [
            {
                id: 3,
                selected_attribute_value_ids: [31],
                attribute_values: [{ id: 31 }, { id: 32 }],
            },
        ],
        parent_exclusions: { 11: [32], 21: [] },
    });
    checkExclusions([parent, child], child);
    expect(valueById(child, 32).excluded).toBe(true);
    expect(valueById(child, 31).excluded).toBe(false);
});

test("checkExclusions: archived combination full match excludes both", () => {
    const p = makeProduct({ archived_combinations: [[11, 21]] });
    checkExclusions([p], p);
    expect(valueById(p, 11).excluded).toBe(true);
    expect(valueById(p, 21).excluded).toBe(true);
});

test("checkExclusions: archived n-1 match disables the remaining value", () => {
    const p = makeProduct({ archived_combinations: [[11, 22]] });
    checkExclusions([p], p);
    expect(valueById(p, 22).excluded).toBe(true);
    expect(valueById(p, 12).excluded).toBe(false);
});

function makeMixedProduct(overrides = {}) {
    return {
        product_tmpl_id: 1,
        attribute_lines: [
            {
                id: 1,
                create_variant: "always",
                selected_attribute_value_ids: [11],
                attribute_values: [{ id: 11 }, { id: 12 }],
            },
            {
                id: 2,
                create_variant: "no_variant",
                selected_attribute_value_ids: [31],
                attribute_values: [{ id: 31 }, { id: 32 }],
            },
        ],
        exclusions: {},
        parent_exclusions: {},
        archived_combinations: [],
        ...overrides,
    };
}

test("getVariantCombination excludes no_variant selections, getCombination keeps them", () => {
    const p = makeMixedProduct();
    expect(getCombination(p)).toEqual([11, 31]);
    expect(getVariantCombination(p)).toEqual([11]);
});

test("checkExclusions: archived variant is disabled despite a no_variant line", () => {
    const p = makeMixedProduct({ archived_combinations: [[12]] });
    checkExclusions([p], p);
    expect(valueById(p, 12).excluded).toBe(true);
    expect(valueById(p, 11).excluded).toBe(false);
    expect(valueById(p, 31).excluded).toBe(false);
    expect(valueById(p, 32).excluded).toBe(false);
});

test("checkExclusions: current selection matching an archived variant, with a no_variant line", () => {
    const p = makeMixedProduct({ archived_combinations: [[11]] });
    checkExclusions([p], p);
    expect(valueById(p, 11).excluded).toBe(true);
});

test("checkExclusions: a multi line's extra selections do not break the match either", () => {
    const p = makeMixedProduct({ archived_combinations: [[12]] });
    p.attribute_lines[1].selected_attribute_value_ids = [31, 32];
    checkExclusions([p], p);
    expect(valueById(p, 12).excluded).toBe(true);
});

test("checkExclusions tolerates a parent product without parent_exclusions", () => {
    const parent = makeProduct({ product_tmpl_id: 1 });
    const child = makeProduct({
        product_tmpl_id: 2,
        parent_product_tmpl_id: 1,
        parent_exclusions: undefined,
    });
    expect(() => checkExclusions([parent, child], child)).not.toThrow();
});

test("checkExclusions recurses into child products", () => {
    const parent = makeProduct({ product_tmpl_id: 1 });
    const child = makeProduct({
        product_tmpl_id: 2,
        parent_product_tmpl_id: 1,
        attribute_lines: [
            {
                id: 3,
                selected_attribute_value_ids: [31],
                attribute_values: [{ id: 31 }, { id: 32 }],
            },
        ],
        exclusions: { 31: [32], 32: [31] },
    });
    checkExclusions([parent, child], parent);
    expect(valueById(child, 32).excluded).toBe(true);
});
