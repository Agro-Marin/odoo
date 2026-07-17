/** @odoo-module native */
import { luxon } from "@web/core/l10n/luxon";
import { registry } from "@web/core/registry";

import { Base } from "./related_models/index.js";
const { DateTime } = luxon;

export class PosPayment extends Base {
    static pythonModel = "pos.payment";

    setup(vals) {
        super.setup(...arguments);
        if (!this.payment_date) {
            this.payment_date = DateTime.now();
        }
        this.amount = vals.amount || 0;
        this.ticket = vals.ticket || "";
    }

    isSelected() {
        return this.pos_order_id?.uiState?.selected_paymentline_uuid === this.uuid;
    }

    setAmount(value) {
        this.pos_order_id.assertEditable();
        this.amount = this.pos_order_id.currency.round(parseFloat(value) || 0);
    }

    getAmount() {
        return this.amount || 0;
    }

    getPaymentStatus() {
        return this.payment_status;
    }

    setPaymentStatus(value) {
        this.payment_status = value;
    }

    isDone() {
        return this.getPaymentStatus()
            ? this.getPaymentStatus() === "done" ||
                  this.getPaymentStatus() === "reversed"
            : true;
    }

    setCashierReceipt(value) {
        this.cashier_receipt = value;
    }

    setReceiptInfo(value) {
        this.ticket += value;
    }

    isElectronic() {
        return Boolean(this.getPaymentStatus());
    }

    async pay() {
        this.setPaymentStatus("waiting");

        // A terminal that throws (network/RPC failure) must not leave the line
        // wedged in "waiting" forever: that status renders no Retry button and
        // blocks adding another electronic payment. Reset to "retry" so the
        // cashier can act, and re-surface the error to the caller.
        let response;
        try {
            response = await this.payment_method_id.payment_terminal.sendPaymentRequest(
                this.uuid,
            );
        } catch (error) {
            this.setPaymentStatus("retry");
            throw error;
        }
        return this.handlePaymentResponse(response);
    }

    handlePaymentResponse(isPaymentSuccessful) {
        if (isPaymentSuccessful) {
            this.setPaymentStatus("done");
            if (this.payment_method_id.payment_method_type !== "qr_code") {
                this.can_be_reversed =
                    this.payment_method_id.payment_terminal.supports_reversals;
            }
        } else {
            this.setPaymentStatus("retry");
        }
        return isPaymentSuccessful;
    }

    /**
     * @param {object} - refundedPaymentLine
     * Override in dependent modules to update the refund payment line with the refunded payment line
     */
    updateRefundPaymentLine(refundedPaymentLine) {}
}

registry.category("pos_available_models").add(PosPayment.pythonModel, PosPayment);
