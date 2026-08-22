/** @odoo-module native */
import { serializeDateTime } from "@web/core/l10n/dates";
import { luxon } from "@web/core/l10n/luxon";
import { ConnectionLostError, RPCError } from "@web/core/network";
import { _t } from "@web/core/translation";
import { AlertDialog, ConfirmationDialog } from "@web/ui/dialog";

import { handleRPCError, showLimitedFunctionalityWarning } from "./error_handlers.js";
import { ask } from "./make_awaitable_dialog.js";
import { logPosMessage } from "./pretty_console_log.js";

/**
 * @param {Object} params
 * @param {Object} params.pos
 * @param {Object} params.order
 * @param {Object} [params.fastPaymentMethod=null]
 */
export default class OrderPaymentValidation {
    constructor({ pos, orderUuid, fastPaymentMethod = null }) {
        this.setup({ pos, orderUuid, fastPaymentMethod });
    }

    setup(vals) {
        this.pos = vals.pos;
        this.orderUuid = vals.orderUuid;
        this.payment_methods_from_config = this.pos.config.payment_method_ids
            .slice()
            .sort((a, b) => a.sequence - b.sequence);
        this.fastPaymentMethod = vals.fastPaymentMethod || null;
    }

    get order() {
        return this.pos.models["pos.order"].getBy("uuid", this.orderUuid);
    }

    get nextPage() {
        if (
            this.pos.config.iface_print_auto &&
            this.pos.config.iface_print_skip_screen
        ) {
            return {
                page: "FeedbackScreen",
                params: {
                    orderUuid: this.order.uuid,
                },
            };
        }

        return {
            page: "ReceiptScreen",
            params: {
                orderUuid: this.order.uuid,
            },
        };
    }

    get paymentLines() {
        return this.order.payment_ids;
    }

    async beforePostPushOrderResolve(order, order_server_ids) {
        return true;
    }

    shouldDownloadInvoice() {
        if (!this.pos.config.canInvoice) {
            return false;
        }
        return true;
    }

    async shouldHideValidationBehindFeedbackScreen() {
        const nextPage = this.nextPage;
        if (nextPage.page === "FeedbackScreen") {
            const waitForFn = async () => {
                try {
                    const response = await this.finalizeValidation();
                    return {
                        ok: !(response instanceof RPCError) && response !== false,
                    };
                } catch (error) {
                    logPosMessage(
                        "OrderPaymentValidation",
                        "shouldHideValidationBehindFeedbackScreen",
                        "Background finalization failed",
                        undefined,
                        [error],
                    );
                    return { ok: false, error };
                }
            };
            nextPage.params.waitFor = waitForFn();
        } else {
            try {
                this.pos.env.services.ui.block();
                const response = await this.finalizeValidation();
                if (response instanceof RPCError) {
                    return false;
                }
            } finally {
                this.pos.env.services.ui.unblock();
            }
        }

        this.pos.navigate(nextPage.page, nextPage.params);
    }

    async validateOrder(isForceValidate) {
        let fastPaymentLine = null;
        if (this.fastPaymentMethod) {
            const res = this.order.addPaymentline(this.fastPaymentMethod);
            fastPaymentLine = res?.data || null;
            this.fastPaymentMethod = null;
        }
        const rollbackFastPayment = () => {
            if (fastPaymentLine) {
                this.order.removePaymentline(fastPaymentLine);
            }
        };
        if ((await this.askBeforeValidation()) === false) {
            rollbackFastPayment();
            return false;
        }
        if ((await this._askForCustomerIfRequired()) === false) {
            rollbackFastPayment();
            return false;
        }
        this.pos.numberBuffer.capture();
        if (!this.checkCashRoundingHasBeenWellApplied()) {
            rollbackFastPayment();
            return false;
        }
        const linesToRemove = this.order.lines.filter((line) => line.canBeRemoved);
        for (const line of linesToRemove) {
            this.order.removeOrderline(line);
        }
        if (await this.isOrderValid(isForceValidate)) {
            const toRemove = [];
            for (const line of this.paymentLines) {
                if (!line.isDone() || line.amount === 0) {
                    toRemove.push(line);
                }
            }

            for (const line of toRemove) {
                this.order.removePaymentline(line);
            }

            await this.shouldHideValidationBehindFeedbackScreen();
            return true;
        }

        rollbackFastPayment();
        return false;
    }

    async finalizeValidation() {
        if (this.order.isPaidWithCash() || this.order.change) {
            this.pos.hardwareProxy.openCashbox();
        }

        this.order.date_order = serializeDateTime(luxon.DateTime.now());
        for (const line of this.paymentLines) {
            if (line.amount === 0) {
                this.order.removePaymentline(line);
            }
        }

        this.pos.addPendingOrder([this.order.id]);
        this.order.state = "paid";
        this.pos.data.localUnsyncedPaidOrderUuids.add(this.order.uuid);

        try {
            const syncOrderResult = await this.pos.syncAllOrders({
                orders: [this.order],
                throw: true,
                force: true,
            });
            if (!syncOrderResult) {
                return false;
            }

            if (this.shouldDownloadInvoice() && this.order.isToInvoice()) {
                if (this.order.raw.account_move) {
                    await this.pos.env.services.account_move.downloadPdf(
                        this.order.raw.account_move,
                    );
                } else {
                    this.pos.dialog.add(AlertDialog, {
                        title: _t("Backend Invoice"),
                        body: _t(
                            "An error occurred while generating an invoice. You can try again from the order list.",
                        ),
                    });
                }
            }

            const postPushOrders = syncOrderResult.filter((order) =>
                order.waitForPushOrder(),
            );
            if (postPushOrders.length > 0) {
                await this.postPushOrderResolve(
                    postPushOrders.map((order) => order.id),
                );
            }

            return await this.afterOrderValidation();
        } catch (error) {
            return this.handleValidationError(error);
        }
    }

    async postPushOrderResolve(ordersServerId) {
        const postPushResult = await this.beforePostPushOrderResolve(
            this.order,
            ordersServerId,
        );
        if (!postPushResult) {
            this.pos.dialog.add(AlertDialog, {
                title: _t("Error: no internet connection."),
                body: _t(
                    "Some, if not all, post-processing after syncing order failed.",
                ),
            });
        }
    }

    async afterOrderValidation() {
        if (!this.pos.config.module_pos_restaurant) {
            this.pos
                .checkPreparationStateAndSentOrderInPreparation(this.order, {
                    orderDone: true,
                })
                .catch((error) => {
                    logPosMessage(
                        "OrderPaymentValidation",
                        "afterOrderValidation",
                        "Failed to send the order to preparation tools",
                        undefined,
                        [error],
                    );
                });
        }

        if (this.order.nb_print === 0 && this.pos.config.iface_print_auto) {
            const invoiced_finalized = this.order.isToInvoice()
                ? this.order.finalized
                : true;
            if (invoiced_finalized) {
                await this.pos.printReceipt({ order: this.order });
            }
        }
    }

    async askBeforeValidation() {
        return true;
    }

    handleValidationError(error) {
        if (error instanceof ConnectionLostError) {
            this.pos.data.synchronizeLocalDataInIndexedDB();
            this.afterOrderValidation();
            showLimitedFunctionalityWarning(this.pos);
            return error;
        } else if (error instanceof RPCError) {
            this.order.state = "draft";
            handleRPCError(error, this.pos.dialog);
        } else {
            throw error;
        }
        return error;
    }

    checkCashRoundingHasBeenWellApplied() {
        const useRound = this.pos.config.hasCashRounding;
        if (!useRound) {
            return true;
        }

        const cashRounding = this.pos.config.rounding_method;
        const order = this.order;
        const currency = this.pos.currency;
        for (const payment of order.payment_ids) {
            if (!payment.payment_method_id.is_cash_count) {
                continue;
            }

            const amountPaid = payment.getAmount();
            const expectedAmountPaid = cashRounding.round(amountPaid);
            if (currency.isZero(expectedAmountPaid - amountPaid)) {
                continue;
            }

            this.pos.dialog.add(AlertDialog, {
                title: _t("Rounding error in payment lines"),
                body: _t(
                    "The amount of your payment lines must be rounded to validate the transaction.\n" +
                        "The rounding precision is %(rounding)s so you should set %(expectedAmount)s as payment amount instead of %(paidAmount)s.",
                    {
                        rounding: cashRounding.rounding.toFixed(
                            this.pos.currency.decimal_places,
                        ),
                        expectedAmount: expectedAmountPaid.toFixed(
                            this.pos.currency.decimal_places,
                        ),
                        paidAmount: amountPaid.toFixed(
                            this.pos.currency.decimal_places,
                        ),
                    },
                ),
            });
            return false;
        }
        return true;
    }

    async isOrderValid(isForceValidate) {
        if (this.order.isRefundInProcess()) {
            return false;
        }

        const inFlightPayment = this.order.payment_ids.find(
            (p) =>
                p.isElectronic() &&
                !p.isDone() &&
                !["pending", "retry"].includes(p.getPaymentStatus()),
        );
        if (this.pos.paymentTerminalInProgress || inFlightPayment) {
            this.pos.dialog.add(AlertDialog, {
                title: _t("Electronic payment in progress"),
                body: _t(
                    "The order cannot be validated while a payment terminal transaction is in progress. Wait for the transaction to finish or cancel it on the payment screen first.",
                ),
            });
            return false;
        }

        if (this.order.getOrderlines().length === 0 && this.order.isToInvoice()) {
            this.pos.dialog.add(AlertDialog, {
                title: _t("Empty Order"),
                body: _t(
                    "There must be at least one product in your order before it can be validated and invoiced.",
                ),
            });
            return false;
        }

        if (
            (this.order.isToInvoice() || this.order.getShippingDate()) &&
            !this.order.getPartner()
        ) {
            const confirmed = await ask(this.pos.dialog, {
                title: _t("Please select the Customer"),
                body: _t(
                    "You need to select the customer before you can invoice or ship an order.",
                ),
            });
            if (confirmed) {
                this.pos.selectPartner();
            }
            return false;
        }

        const partner = this.order.getPartner();
        if (
            this.order.getShippingDate() &&
            !(partner.name && partner.street && partner.city && partner.country_id)
        ) {
            this.pos.dialog.add(AlertDialog, {
                title: _t("Incorrect address for shipping"),
                body: _t("The selected customer needs an address."),
            });
            return false;
        }

        const missingRequirement = this.order.getMissingPresetRequirement();
        if (missingRequirement) {
            const { field, message } = missingRequirement;
            this.pos.dialog.add(AlertDialog, {
                title: field ? _t("%s required", field) : _t("Missing required"),
                body: message || _t("Some required information is missing."),
            });
            return false;
        }

        if (
            !this.pos.currency.isZero(this.order.priceIncl) &&
            this.order.payment_ids.length === 0
        ) {
            this.pos.notification.add(
                _t("Select a payment method to validate the order."),
            );
            return false;
        }

        if (!this.order.isPaid()) {
            return false;
        }

        if (
            Math.abs(
                this.order.priceIncl -
                    this.order.amountPaid +
                    this.order.appliedRounding,
            ) > 0.00001
        ) {
            if (!this.pos.models["pos.payment.method"].some((pm) => pm.is_cash_count)) {
                this.pos.dialog.add(AlertDialog, {
                    title: _t("Cannot return change without a cash payment method"),
                    body: _t(
                        "There is no cash payment method available in this point of sale to handle the change.\n\n Please pay the exact amount or add a cash payment method in the point of sale configuration",
                    ),
                });
                return false;
            }
        }

        if (
            !isForceValidate &&
            this.order.priceIncl > 0 &&
            this.order.priceIncl * 1000 < this.order.amountPaid
        ) {
            this.pos.dialog.add(ConfirmationDialog, {
                title: _t("Please Confirm Large Amount"),
                body:
                    _t("Are you sure that the customer wants to  pay") +
                    " " +
                    this.pos.env.utils.formatCurrency(this.order.amountPaid) +
                    " " +
                    _t("for an order of") +
                    " " +
                    this.pos.env.utils.formatCurrency(this.order.priceIncl) +
                    " " +
                    _t('? Clicking "Confirm" will validate the payment.'),
                confirm: () => this.validateOrder(true),
            });
            return false;
        }

        if (!this.order._isValidEmptyOrder()) {
            return false;
        }

        return true;
    }

    async _askForCustomerIfRequired() {
        const splitPayments = this.order.payment_ids.filter(
            (payment) => payment.payment_method_id.split_transactions,
        );
        if (splitPayments.length && !this.order.getPartner()) {
            const paymentMethod = splitPayments[0].payment_method_id;
            const confirmed = await ask(this.pos.dialog, {
                title: _t("Customer Required"),
                body: _t(
                    "Customer is required for %s payment method.",
                    paymentMethod.name,
                ),
            });
            if (confirmed) {
                await this.pos.selectPartner();
            }
            return false;
        }
    }
}
