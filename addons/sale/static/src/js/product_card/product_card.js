/** @odoo-module native */
import { Component } from "@odoo/owl";

import { BadgeExtraPrice } from "../badge_extra_price/badge_extra_price.js";
import { ProductProduct } from "../models/product_product.js";

export class ProductCard extends Component {
    static template = "sale.ProductCard";
    static components = { BadgeExtraPrice };
    static props = {
        product: ProductProduct,
        extraPrice: { type: Number, optional: true },
        onClick: Function,
        isSelected: { type: Boolean, optional: true },
        isConfigurable: { type: Boolean, optional: true },
    };

    /**
     * @param {KeyboardEvent} event
     */
    onKeydown(event) {
        if (event.key !== "Enter" && event.key !== " ") {
            return;
        }
        event.preventDefault();
        this.props.onClick();
    }

    /**
     * @param {ProductTemplateAttributeLine} ptal
     * @return {Boolean}
     */
    shouldShowPtal(ptal) {
        return (
            ptal.selected_ptavs.length > 0 &&
            (ptal.hasSelectedCustomPtav || ptal.create_variant === "no_variant")
        );
    }
}
