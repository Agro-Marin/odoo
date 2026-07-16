/** @odoo-module native */
import { toRaw } from "@odoo/owl";
import { formatCurrency } from "@point_of_sale/app/models/utils/currency";
import { logPosMessage } from "@point_of_sale/app/utils/pretty_console_log";

const CONSOLE_COLOR = "#FF8269";

/**
 * This module provides functions to format order and order line data for customer display.
 * The goal is to format data in a way that avoids loading all models in the customer display.
 */

export class CustomerDisplayPosAdapter {
    constructor() {
        this.setup();
    }

    setup() {
        this.data = {};
        this.channel = new BroadcastChannel("UPDATE_CUSTOMER_DISPLAY");
    }

    dispatch(pos) {
        this.channel.postMessage(JSON.parse(JSON.stringify(this.data)));
        // The server call only re-notifies the bus channel
        // "UPDATE_CUSTOMER_DISPLAY-<device_uuid>". The uuid is created when a
        // remote display is provisioned from this device's navbar; without it
        // no display can be listening, so the RPC (per order mutation!) would
        // be pure overhead.
        const deviceUuid = localStorage.getItem("device_uuid");
        if (!deviceUuid) {
            return;
        }
        pos.data
            .call("pos.config", "update_customer_display", [
                [pos.config.id],
                this.data,
                deviceUuid,
            ])
            .catch((error) => {
                logPosMessage(
                    "CustomerDisplay",
                    "dispatch",
                    "Failed to update customer display",
                    CONSOLE_COLOR,
                    [error],
                );
            });
    }

    formatEmpty() {
        // Payload shown when no order is selected: without it the display
        // kept rendering the previous order after it was closed/deleted.
        this.data = {
            finalized: false,
            general_customer_note: "",
            amount: false,
            subtotal: false,
            amountTaxes: false,
            change: false,
            paymentLines: [],
            lines: [],
            qrPaymentData: null,
        };
    }

    formatOrderData(order) {
        this.currency = order.currency;
        this.data = {
            finalized: order.finalized,
            general_customer_note: order.general_customer_note,
            amount: order.currencyDisplayPriceIncl,
            subtotal:
                order.config_id.iface_tax_included !== "total" &&
                order.prices.taxDetails.has_tax_groups &&
                order.currencyDisplayPriceExcl,
            amountTaxes:
                order.prices.taxDetails.has_tax_groups && order.currencyAmountTaxes,
            change: order.change && formatCurrency(order.change, order.currency),
            paymentLines: order.payment_ids.map((pl) => this.getPaymentData(pl)),
            lines: order.lines.map((l) => this.getOrderlineData(l)),
            qrPaymentData: toRaw(order.getSelectedPaymentline()?.qrPaymentData),
        };
    }

    getOrderlineData(line) {
        return {
            productId: line.product_id.id,
            taxGroupLabels: line.taxGroupLabels,
            discount: line.getDiscountStr(),
            customerNote: line.getCustomerNote() || "",
            internalNote: line.getNote() || "[]",
            productName: line.getFullProductName(),
            price: line.currencyDisplayPrice,
            qty: line.getQuantityStr().qtyStr,
            unit: line.product_id.uom_id ? line.product_id.uom_id.name : "",
            unitPrice: line.currencyDisplayPriceUnit,
            packLotLines: line.packLotLines,
            comboParent: line.combo_parent_id?.getFullProductName?.() || "",
            price_without_discount: formatCurrency(
                line.displayPriceNoDiscount,
                line.currency,
            ),
            isSelected: line.isSelected(),
        };
    }

    getPaymentData(payment) {
        return {
            name: payment.payment_method_id.name,
            amount: formatCurrency(payment.amount, this.currency),
        };
    }
}
