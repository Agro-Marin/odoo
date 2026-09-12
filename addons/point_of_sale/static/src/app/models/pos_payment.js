/** @odoo-module native */
import { makeLogger } from "@web/core/debug/debug_logger";
import { luxon } from "@web/core/l10n/luxon";
import { registry } from "@web/core/registry";

import { Base } from "./related_models/index.js";
const { DateTime } = luxon;
const log = makeLogger("pos.payment");

export class PosPayment extends Base {
    static pythonModel = "pos.payment";

    setup(vals) {
        super.setup(...arguments);
        if (!this.payment_date) {
            this.payment_date = DateTime.now();
        }
        this.amount = vals.amount ?? this.amount ?? 0;
        this.ticket = vals.ticket ?? this.ticket ?? "";
    }

    isSelected() {
        return this.pos_order_id?.uiState?.selected_paymentline_uuid === this.uuid;
    }

    setAmount(value) {
        this.pos_order_id.assertEditable();
        log.logic("setAmount", () => ({
            payment: this.uuid,
            order: this.pos_order_id.uuid,
            from: this.amount,
            to: value,
        }));
        this.amount = this.pos_order_id.currency.round(parseFloat(value) || 0);
    }

    getAmount() {
        return this.amount || 0;
    }

    getPaymentStatus() {
        return this.payment_status;
    }

    setPaymentStatus(value) {
        log.lifecycle("setPaymentStatus", () => ({
            payment: this.uuid,
            order: this.pos_order_id?.uuid,
            from: this.payment_status,
            to: value,
        }));
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
        const endPay = log.perf("pay");
        log.pipeline("pay", () => ({
            payment: this.uuid,
            order: this.pos_order_id?.uuid,
            method: this.payment_method_id.id,
            terminal: this.payment_method_id.use_payment_terminal,
            amount: this.amount,
        }));

        let response;
        try {
            response = await this.payment_method_id.payment_terminal.sendPaymentRequest(
                this.uuid,
            );
        } catch (error) {
            endPay({ payment: this.uuid, error: error?.message });
            this.setPaymentStatus("retry");
            throw error;
        }
        endPay({ payment: this.uuid, response });
        return this.handlePaymentResponse(response);
    }

    handlePaymentResponse(isPaymentSuccessful) {
        log.logic("handlePaymentResponse", () => ({
            payment: this.uuid,
            successful: Boolean(isPaymentSuccessful),
            type: this.payment_method_id.payment_method_type,
        }));
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
     * @param {object} -
     */
    updateRefundPaymentLine(refundedPaymentLine) {}
}

registry.category("pos_available_models").add(PosPayment.pythonModel, PosPayment);
