/** @odoo-module native */
import { Component } from "@odoo/owl";
import { formatCurrency } from "@web/core/currency";
import { _t } from "@web/core/translation";

import { BadgeExtraPrice } from "../badge_extra_price/badge_extra_price.js";
import { getSelectedCustomPtav } from "../sale_utils.js";

export class ProductTemplateAttributeLine extends Component {
    static components = { BadgeExtraPrice };
    static template = "sale.ProductTemplateAttributeLine";
    static props = {
        productTmplId: Number,
        id: Number,
        attribute: {
            type: Object,
            shape: {
                id: Number,
                name: String,
                display_type: {
                    type: String,
                    validate: (type) =>
                        [
                            "color",
                            "multi",
                            "pills",
                            "radio",
                            "select",
                            "image",
                        ].includes(type),
                },
            },
        },
        attribute_values: {
            type: Array,
            element: {
                type: Object,
                shape: {
                    id: Number,
                    name: String,
                    html_color: [Boolean, String],
                    image: [Boolean, String],
                    is_custom: Boolean,
                    price_extra: Number,
                    excluded: { type: Boolean, optional: true },
                },
            },
        },
        selected_attribute_value_ids: { type: Array, element: Number },
        create_variant: {
            type: String,
            validate: (type) => ["always", "dynamic", "no_variant"].includes(type),
        },
        customValue: { type: [{ value: false }, String], optional: true },
        show_extra_price: { type: Boolean },
    };

    /**
     * @param {Event} event
     */
    updateSelectedPTAV(event) {
        this.env.updateProductTemplateSelectedPTAV(
            this.props.productTmplId,
            this.props.id,
            event.target.value,
            this.props.attribute.display_type === "multi",
        );
    }

    /**
     * @param {Event} event
     */
    updateCustomValue(event) {
        this.env.updatePTAVCustomValue(
            this.props.productTmplId,
            this.props.selected_attribute_value_ids[0],
            event.target.value,
        );
    }

    /**
     * @return {String}
     */
    getPTAVTemplate() {
        switch (this.props.attribute.display_type) {
            case "select":
                return "sale.ptav_select";
            case "radio":
                return "sale.ptav_radio";
            case "pills":
                return "sale.ptav_pills";
            case "color":
                return "sale.ptav_color";
            case "multi":
                return "sale.ptav_multi";
            case "image":
                return "sale.ptav_image";
        }
    }

    /**
     * @param {Object} ptav
     * @return {String}
     */
    getPTAVSelectName(ptav) {
        if (ptav.price_extra) {
            const sign = ptav.price_extra > 0 ? "+" : "-";
            const price = formatCurrency(
                Math.abs(ptav.price_extra),
                this.env.currency.id,
            );
            return ptav.name + " (" + sign + " " + price + ")";
        } else {
            return ptav.name;
        }
    }

    /**
     * @return {Boolean}
     */
    isSelectedPTAVCustom() {
        return !!getSelectedCustomPtav(this.props);
    }

    get showValuesChoice() {
        return (
            (this.env.canChangeVariant || this.props.create_variant === "no_variant") &&
            (this.props.attribute_values.length > 1 ||
                this.props.attribute.display_type === "multi")
        );
    }

    get customValuePlaceholder() {
        return _t("Enter a customized value");
    }

    /**
     * @return {Boolean}
     */
    hasPTAVCustom() {
        return this.props.attribute_values.some((ptav) => ptav.is_custom);
    }
}
