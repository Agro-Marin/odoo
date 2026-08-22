/** @odoo-module native */
import { ProductTemplateAttributeValue } from "./product_template_attribute_value.js";

export class ProductTemplateAttributeLine {
    /**
     * @param {number} id
     * @param {string} name
     * @param {'always'|'dynamic'|'no_variant'} create_variant
     * @param {ProductTemplateAttributeValue[]|object[]} selected_ptavs
     */
    constructor({ id, name, create_variant, selected_ptavs }) {
        this.id = id;
        this.name = name;
        this.create_variant = create_variant;
        this.selected_ptavs = selected_ptavs.map(
            (ptav) => new ProductTemplateAttributeValue(ptav),
        );
    }

    /**
     * @return {ProductTemplateAttributeLine}
     */
    static fromProductConfiguratorPtal(productConfiguratorPtal) {
        const selectedPtavIds = new Set(
            productConfiguratorPtal.selected_attribute_value_ids,
        );
        const selectedPtavs = productConfiguratorPtal.attribute_values
            .filter((ptav) => selectedPtavIds.has(ptav.id))
            .map(
                (ptav) =>
                    new ProductTemplateAttributeValue({
                        id: ptav.id,
                        name: ptav.name,
                        price_extra: ptav.price_extra,
                        custom_value: ptav.is_custom
                            ? productConfiguratorPtal.customValue
                            : undefined,
                    }),
            );
        return new ProductTemplateAttributeLine({
            id: productConfiguratorPtal.id,
            name: productConfiguratorPtal.attribute.name,
            create_variant: productConfiguratorPtal.create_variant,
            selected_ptavs: selectedPtavs,
        });
    }

    /**
     * @return {Number}
     */
    get selectedPtavsPriceExtra() {
        return this.selected_ptavs.reduce((price, ptav) => price + ptav.price_extra, 0);
    }

    /**
     * @return {Boolean}
     */
    get hasSelectedCustomPtav() {
        return !!this.selectedCustomPtav;
    }

    /**
     * @return {ProductTemplateAttributeValue|undefined}
     */
    get selectedCustomPtav() {
        return this.selected_ptavs.find((ptav) => ptav.custom_value);
    }

    /**
     * @return {String}
     */
    get ptalDisplayName() {
        const selectedPtavNames = this.selected_ptavs
            .map((ptav) => ptav.name)
            .join(", ");
        let ptalDisplayName = `${this.name}: ${selectedPtavNames}`;
        const customPtav = this.selectedCustomPtav;
        if (customPtav) {
            ptalDisplayName += ` (${customPtav.custom_value})`;
        }
        return ptalDisplayName;
    }
}
