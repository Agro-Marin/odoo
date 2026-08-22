/** @odoo-module native */
import { Component } from "@odoo/owl";
import { formatCurrency } from "@web/core/currency";

export class BadgeExtraPrice extends Component {
    static template = "sale.BadgeExtraPrice";
    static props = {
        price: Number,
        currencyId: Number,
    };

    /**
     * @return {String}
     */
    getFormattedPrice() {
        return formatCurrency(Math.abs(this.props.price), this.props.currencyId);
    }
}
