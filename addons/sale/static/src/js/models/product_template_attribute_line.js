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
     * Construct a ProductTemplateAttributeLine from the provided "product configurator"-shaped
     * PTAL.
     *
     * @param productConfiguratorPtal The "product configurator"-shaped PTAL.
     * @return {ProductTemplateAttributeLine} The corresponding ProductTemplateAttributeLine.
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
                        // `customValue` is scoped to the PTAL, but it belongs to the one
                        // PTAV that asked for it. A `multi` attribute can have several
                        // values selected alongside its `is_custom` one; copying the
                        // value onto all of them made `selectedCustomPtavs` emit a
                        // `product.attribute.custom.value` per selected PTAV, which the
                        // server then prints as an extra line on the order line.
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
     * Return the extra price of the selected PTAVs.
     *
     * @return {Number} The extra price of the selected PTAVs.
     */
    get selectedPtavsPriceExtra() {
        return this.selected_ptavs.reduce((price, ptav) => price + ptav.price_extra, 0);
    }

    /**
     * Check whether this PTAL has selected custom PTAVs.
     *
     * @return {Boolean} Whether this PTAL has selected custom PTAVs.
     */
    get hasSelectedCustomPtav() {
        return !!this.selectedCustomPtav;
    }

    /**
     * Return the selected PTAV carrying a custom value, if any.
     *
     * A PTAL has at most one, by design. Reading it by lookup rather than as
     * `selected_ptavs[0]` is what makes a `multi` attribute work: its custom value is
     * rarely the first of several selected values.
     *
     * @return {ProductTemplateAttributeValue|undefined} The custom PTAV, if any.
     */
    get selectedCustomPtav() {
        return this.selected_ptavs.find((ptav) => ptav.custom_value);
    }

    /**
     * Return the display name of this PTAL.
     *
     * @return {String} The display name of this PTAL.
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
