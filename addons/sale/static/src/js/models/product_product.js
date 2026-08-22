/** @odoo-module native */
import { ProductTemplateAttributeLine } from "./product_template_attribute_line.js";

export class ProductProduct {
    constructor(...args) {
        this.setup(...args);
    }

    /**
     * @param {number} id
     * @param {number} product_tmpl_id
     * @param {string} display_name
     * @param {ProductTemplateAttributeLine[]|object[]} ptals
     * @param {string} image_src
     * @param {string} description
     */
    setup({ id, product_tmpl_id, display_name, ptals, image_src, description }) {
        this.id = id;
        this.product_tmpl_id = product_tmpl_id;
        this.display_name = display_name;
        this.ptals = ptals.map((ptal) => new ProductTemplateAttributeLine(ptal));
        this.image_src = image_src;
        this.description = description;
    }

    /**
     * @return {ProductTemplateAttributeLine[]}
     */
    get noVariantPtals() {
        return this.ptals.filter((ptal) => ptal.create_variant === "no_variant");
    }

    /**
     * @return {Number}
     */
    get selectedNoVariantPtavsPriceExtra() {
        return this.noVariantPtals.reduce(
            (price, ptal) => price + ptal.selectedPtavsPriceExtra,
            0,
        );
    }

    /**
     * @return {Number[]}
     */
    get selectedPtavIds() {
        return this.ptals.flatMap((ptal) => ptal.selected_ptavs).map((ptav) => ptav.id);
    }

    /**
     * @return {Number[]}
     */
    get selectedNoVariantPtavIds() {
        return this.noVariantPtals
            .flatMap((ptal) => ptal.selected_ptavs)
            .map((ptav) => ptav.id);
    }

    /**
     * @return {{id: Number, value: String}[]}
     */
    get selectedCustomPtavs() {
        return this.ptals
            .map((ptal) => ptal.selectedCustomPtav)
            .filter(Boolean)
            .map((ptav) => ({
                id: ptav.id,
                value: ptav.custom_value,
            }));
    }
}
