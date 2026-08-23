// @ts-check
/** @odoo-module native */

import { Component } from "@odoo/owl";
import { _t } from "@web/core/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class PriceHistoryWidget extends Component {
    static template = "base_order.PriceHistoryWidget";
    static props = {
        record: { type: Object },
        action: { type: String },
        readonly: { type: Boolean, optional: true },
    };

    setup() {
        this.actionService = useService("action");
    }

    /** @returns {boolean} */
    get isAvailable() {
        return Boolean(this.props.record.data.product_id);
    }

    async openPriceHistory() {
        if (!this.isAvailable) {
            return;
        }
        const { data, resId } = this.props.record;
        await this.actionService.doAction(this.props.action, {
            additionalContext: {
                default_line_id: resId,
                default_partner_id: data.partner_id ? data.partner_id.id : false,
                default_product_id: data.product_id ? data.product_id.id : false,
            },
        });
    }
}

/** @type {import("registries").ViewWidgetsRegistryItemShape} */
export const priceHistoryWidget = {
    component: PriceHistoryWidget,
    listViewWidth: 26,
    fieldDependencies: [
        { name: "product_id", type: "many2one" },
        { name: "partner_id", type: "many2one" },
    ],
    supportedOptions: [
        {
            name: "action",
            label: _t("Action"),
            type: "string",
            help: _t("XML id of the price history wizard action to open."),
        },
    ],
    extractProps: ({ options }) => ({ action: options.action }),
};

registry.category("view_widgets").add("price_history", priceHistoryWidget);
