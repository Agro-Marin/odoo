/** @odoo-module native */
import { Component } from "@odoo/owl";
import { formatCurrency } from "@web/core/currency";

export class AddToCartNotification extends Component {
    static template = "website_sale.addToCartNotification";
    static props = {
        lines: {
            type: Array,
            element: {
                type: Object,
                shape: {
                    id: Number,
                    linked_line_id: { type: Number, optional: true },
                    image_url: String,
                    quantity: Number,
                    uom_name: { type: String, optional: true },
                    combination_name: { type: String, optional: true },
                    name: String,
                    description: { type: String, optional: true },
                    price_total: Number,
                },
            },
        },
        currency_id: Number,
    };

    /**
     * @return {Object[]}
     */
    get mainLines() {
        return this.props.lines.filter((line) => !line.linked_line_id);
    }

    /**
     * @param {Number} lineId
     * @return {Object[]}
     */
    getLinkedLines(lineId) {
        return this.props.lines.filter((line) => line.linked_line_id === lineId);
    }

    /**
     * @param {Object} line
     * @return {String}
     */
    getFormattedPrice(line) {
        const linkedLines = this.getLinkedLines(line.id);
        const price = linkedLines.length
            ? linkedLines.reduce(
                  (price, linkedLine) => price + linkedLine.price_total,
                  0,
              )
            : line.price_total;
        return formatCurrency(price, this.props.currency_id);
    }
}
