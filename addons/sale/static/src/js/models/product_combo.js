/** @odoo-module native */
import { ProductComboItem } from "./product_combo_item.js";

export class ProductCombo {
    /**
     * @param {number} id
     * @param {string} name
     * @param {ProductComboItem[]|object[]} combo_items
     */
    constructor({ id, name, combo_items }) {
        this.id = id;
        this.name = name;
        this.combo_items = combo_items.map((item) => new ProductComboItem(item));
    }

    /**
     * @return {ProductComboItem|undefined}
     */
    get selectedComboItem() {
        return this.combo_items.find((item) => item.is_selected);
    }

    /**
     * @return {ProductComboItem|undefined}
     */
    get preselectedComboItem() {
        return this.combo_items.find((item) => item.is_preselected);
    }

    /**
     * @return {Boolean}
     */
    get isConfigurable() {
        return !this.combo_items.some((item) => item.is_preselected);
    }

    /**
     * @return {Boolean}
     */
    get isEmpty() {
        return this.combo_items.length === 0;
    }
}
