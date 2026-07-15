import { expect, test } from "@odoo/hoot";
import { ProductProduct } from "@sale/js/models/product_product";
import { ProductCombo } from "@sale/js/models/product_combo";
import { ProductComboItem } from "@sale/js/models/product_combo_item";
import { ProductTemplateAttributeLine } from "@sale/js/models/product_template_attribute_line";

function makeProduct(overrides = {}) {
    return new ProductProduct({
        id: 7,
        product_tmpl_id: 3,
        display_name: "Chair",
        image_src: "",
        description: "",
        ptals: [
            {
                id: 1,
                name: "Color",
                create_variant: "no_variant",
                selected_ptavs: [{ id: 11, name: "Red", price_extra: 5, custom_value: undefined }],
            },
            {
                id: 2,
                name: "Legs",
                create_variant: "always",
                selected_ptavs: [{ id: 22, name: "Wood", price_extra: 10, custom_value: undefined }],
            },
            {
                id: 3,
                name: "Engraving",
                create_variant: "no_variant",
                selected_ptavs: [{ id: 33, name: "Text", price_extra: 2, custom_value: "Hi" }],
            },
        ],
        ...overrides,
    });
}

test("ProductProduct.selectedPtavIds spans all ptals", () => {
    expect(makeProduct().selectedPtavIds).toEqual([11, 22, 33]);
});

test("ProductProduct.noVariantPtals filters create_variant", () => {
    expect(makeProduct().noVariantPtals.map((p) => p.id)).toEqual([1, 3]);
});

test("ProductProduct.selectedNoVariantPtavIds", () => {
    expect(makeProduct().selectedNoVariantPtavIds).toEqual([11, 33]);
});

test("ProductProduct.selectedNoVariantPtavsPriceExtra sums no_variant extras only", () => {
    expect(makeProduct().selectedNoVariantPtavsPriceExtra).toBe(7);
});

test("ProductProduct.selectedCustomPtavs returns only custom values", () => {
    expect(makeProduct().selectedCustomPtavs).toEqual([{ id: 33, value: "Hi" }]);
});

test("PTAL.hasSelectedCustomPtav: '0' string is truthy, '' is not", () => {
    const withZero = new ProductTemplateAttributeLine({
        id: 9, name: "Qty", create_variant: "no_variant",
        selected_ptavs: [{ id: 91, name: "x", price_extra: 0, custom_value: "0" }],
    });
    const empty = new ProductTemplateAttributeLine({
        id: 9, name: "Qty", create_variant: "no_variant",
        selected_ptavs: [{ id: 91, name: "x", price_extra: 0, custom_value: "" }],
    });
    expect(withZero.hasSelectedCustomPtav).toBe(true);
    expect(empty.hasSelectedCustomPtav).toBe(false);
});

test("PTAL.ptalDisplayName includes custom value", () => {
    const ptal = new ProductTemplateAttributeLine({
        id: 9, name: "Engraving", create_variant: "no_variant",
        selected_ptavs: [{ id: 91, name: "Text", price_extra: 0, custom_value: "Hi" }],
    });
    expect(ptal.ptalDisplayName).toBe("Engraving: Text (Hi)");
});

test("PTAL.fromProductConfiguratorPtal maps configurator shape", () => {
    const ptal = ProductTemplateAttributeLine.fromProductConfiguratorPtal({
        id: 5,
        attribute: { name: "Color" },
        create_variant: "no_variant",
        selected_attribute_value_ids: [12],
        customValue: "custom",
        attribute_values: [
            { id: 11, name: "Red", price_extra: 1 },
            { id: 12, name: "Blue", price_extra: 2 },
        ],
    });
    expect(ptal.name).toBe("Color");
    expect(ptal.selected_ptavs.map((p) => p.id)).toEqual([12]);
    expect(ptal.selected_ptavs[0].custom_value).toBe("custom");
});

test("ProductComboItem.totalExtraPrice = item extra + no_variant extras", () => {
    const item = new ProductComboItem({
        id: 1, extra_price: 3, is_preselected: false, is_selected: true, is_configurable: false,
        product: {
            id: 7, product_tmpl_id: 3, display_name: "Chair", image_src: "", description: "",
            ptals: [{
                id: 1, name: "Color", create_variant: "no_variant",
                selected_ptavs: [{ id: 11, name: "Red", price_extra: 5 }],
            }],
        },
    });
    expect(item.totalExtraPrice).toBe(8);
});

test("ProductComboItem.deepCopy is independent of the original", () => {
    const item = new ProductComboItem({
        id: 1, extra_price: 3, is_preselected: false, is_selected: true, is_configurable: false,
        product: {
            id: 7, product_tmpl_id: 3, display_name: "Chair", image_src: "", description: "",
            ptals: [{
                id: 1, name: "Color", create_variant: "no_variant",
                selected_ptavs: [{ id: 11, name: "Red", price_extra: 5 }],
            }],
        },
    });
    const copy = item.deepCopy();
    copy.product.ptals[0].selected_ptavs[0].price_extra = 999;
    expect(copy instanceof ProductComboItem).toBe(true);
    expect(item.product.ptals[0].selected_ptavs[0].price_extra).toBe(5);
});

test("ProductCombo.isConfigurable is false when an item is preselected", () => {
    const combo = new ProductCombo({
        id: 1, name: "c",
        combo_items: [{
            id: 1, extra_price: 0, is_preselected: true, is_selected: false, is_configurable: false,
            product: { id: 1, product_tmpl_id: 1, display_name: "a", ptals: [] },
        }],
    });
    expect(combo.isConfigurable).toBe(false);
    expect(combo.preselectedComboItem.id).toBe(1);
});
