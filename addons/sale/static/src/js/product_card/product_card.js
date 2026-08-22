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
     * Activate the card from the keyboard.
     *
     * The card is the combo configurator's primary control, so it has to behave like the
     * button it is: both Enter and Space activate it, and Space is prevented from also
     * scrolling the dialog. This used to hang off `keypress` — deprecated, and it never
     * matched Enter because the handler only tested for `Space`.
     *
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
     * Check whether the provided PTAL should be shown in this card.
     *
     * @param {ProductTemplateAttributeLine} ptal The PTAL to check.
     * @return {Boolean} Whether to show the PTAL.
     */
    shouldShowPtal(ptal) {
        return (
            ptal.selected_ptavs.length > 0 &&
            (ptal.hasSelectedCustomPtav || ptal.create_variant === "no_variant")
        );
    }
}
