/** @odoo-module native */
import { ProductProduct } from "./product_product.js";

export class ProductComboItem {
    /**
     * @param {number} id
     * @param {number} extra_price
     * @param {boolean} is_preselected
     * @param {boolean} is_selected
     * @param {boolean} is_configurable
     * @param {ProductProduct|object} product
     */
    constructor({
        id,
        extra_price,
        is_preselected,
        is_selected,
        is_configurable,
        product,
    }) {
        this.id = id;
        this.extra_price = extra_price;
        this.is_preselected = is_preselected;
        this.is_selected = is_selected;
        this.is_configurable = is_configurable;
        this.product = new ProductProduct(product);
    }

    /**
     * @return {Number}
     */
    get totalExtraPrice() {
        return this.extra_price + this.product.selectedNoVariantPtavsPriceExtra;
    }

    /**
     * @return {ProductComboItem}
     */
    deepCopy() {
        return new ProductComboItem(structuredClone({ ...this }));
    }
}
