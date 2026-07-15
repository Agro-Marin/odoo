import { expect, test } from "@odoo/hoot";
import {
    areSaleOrderLinesLinked,
    getSelectedCustomPtav,
    serializeComboItem,
} from "@sale/js/sale_utils";

test("serializeComboItem produces the server shape", () => {
    const comboItem = {
        id: 1,
        product: {
            id: 7,
            selectedNoVariantPtavIds: [11],
            selectedCustomPtavs: [{ id: 33, value: "Hi" }],
        },
    };
    expect(serializeComboItem(comboItem)).toEqual({
        combo_item_id: 1,
        product_id: 7,
        no_variant_attribute_value_ids: [11],
        product_custom_attribute_values: [
            { custom_product_template_attribute_value_id: 33, custom_value: "Hi" },
        ],
    });
});

test("getSelectedCustomPtav returns the selected custom PTAV", () => {
    const ptal = {
        selected_attribute_value_ids: [33],
        attribute_values: [
            { id: 22, is_custom: false },
            { id: 33, is_custom: true },
        ],
    };
    expect(getSelectedCustomPtav(ptal).id).toBe(33);
});

test("getSelectedCustomPtav returns undefined when selected value isn't custom", () => {
    const ptal = {
        selected_attribute_value_ids: [22],
        attribute_values: [
            { id: 22, is_custom: false },
            { id: 33, is_custom: true },
        ],
    };
    expect(getSelectedCustomPtav(ptal)).toBe(undefined);
});

test("areSaleOrderLinesLinked matches saved lines by resId", () => {
    const linking = { data: { linked_line_id: { id: 99 } }, isNew: false };
    const linked = { data: {}, isNew: false, resId: 99 };
    expect(areSaleOrderLinesLinked(linking, linked)).toBe(true);
});

test("areSaleOrderLinesLinked matches new lines by virtual_id", () => {
    const linking = { data: { linked_virtual_id: "v1" }, isNew: false };
    const linked = { data: { virtual_id: "v1" }, isNew: true };
    expect(areSaleOrderLinesLinked(linking, linked)).toBe(true);
});

test("areSaleOrderLinesLinked is falsy for an unlinked line (no throw)", () => {
    const linking = { data: { linked_line_id: false, linked_virtual_id: false }, isNew: false };
    const linked = { data: { virtual_id: false }, isNew: false, resId: 99 };
    expect(!!areSaleOrderLinesLinked(linking, linked)).toBe(false);
});
