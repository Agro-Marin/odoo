/** @odoo-module native */
import { Component, useState } from "@odoo/owl";
import { Input } from "@point_of_sale/app/components/inputs/input/input";
import { SaleDetailsButton } from "@point_of_sale/app/components/navbar/sale_details_button/sale_details_button";
import { PaymentMethodBreakdown } from "@point_of_sale/app/components/payment_method_breakdown/payment_method_breakdown";
import { MoneyDetailsPopup } from "@point_of_sale/app/components/popups/money_details_popup/money_details_popup";
import { useAsyncLockedMethod } from "@point_of_sale/app/hooks/hooks";
import { usePos } from "@point_of_sale/app/hooks/pos_hook";
import { ask } from "@point_of_sale/app/utils/make_awaitable_dialog";
import { makeLogger } from "@web/core/debug/debug_logger";
import { useLifecycleLog } from "@web/core/debug/logger_hooks";
import { luxon } from "@web/core/l10n/luxon";
import { ConnectionLostError } from "@web/core/network";
import { parseFloat } from "@web/core/parsers";
import { _t } from "@web/core/translation";
import { useService } from "@web/core/utils/hooks";
import { AlertDialog, ConfirmationDialog, Dialog } from "@web/ui/dialog";
import { FormViewDialog } from "@web/views/view_dialogs";
const { DateTime } = luxon;
const log = makeLogger("pos.popup.closing");

export class ClosePosPopup extends Component {
    static components = {
        SaleDetailsButton,
        Input,
        Dialog,
        PaymentMethodBreakdown,
    };
    static template = "point_of_sale.ClosePosPopup";
    static props = [
        "orders_details",
        "opening_notes",
        "default_cash_details",
        "non_cash_payment_methods",
        "is_manager",
        "amount_authorized_diff",
        "close",
    ];

    setup() {
        useLifecycleLog(log);
        this.pos = usePos();
        this.report = useService("report");
        this.hardwareProxy = useService("hardware_proxy");
        this.dialog = useService("dialog");
        this.ui = useService("ui");
        this.state = useState(this.getInitialState());
        this.confirm = useAsyncLockedMethod(this.confirm);
        log.lifecycle("[session:close] opened", () => ({
            session: this.pos.session?.id,
            cashControl: this.pos.config.cash_control,
            isManager: this.props.is_manager,
            authorizedDiff: this.props.amount_authorized_diff,
            nonCashMethods: this.props.non_cash_payment_methods.length,
            ordersForNextDays: this.orderForNextDays,
        }));
    }
    autoFillCashCount() {
        const count = this.props.default_cash_details.amount;
        this.state.payments[this.props.default_cash_details.id].counted =
            this.env.utils.formatCurrency(count, false);
        this.setManualCashInput(count);
    }
    autoFillPMCount(paymentId) {
        const pm = this.props.non_cash_payment_methods.find(
            (pm) => pm.id === paymentId,
        );
        if (pm) {
            this.state.payments[paymentId].counted = this.env.utils.formatCurrency(
                pm.amount,
                false,
            );
        }
    }
    get cashMoveData() {
        const { total, moves } = this.props.default_cash_details.moves.reduce(
            (acc, move, i) => {
                acc.total += move.amount;
                acc.moves.push({
                    id: i,
                    name: move.name,
                    amount: move.amount,
                });
                return acc;
            },
            { total: 0, moves: [] },
        );
        return { total, moves };
    }
    get orderForNextDays() {
        const today = DateTime.now();
        return this.pos.models["pos.order"].filter(
            (o) => o.lines.length > 0 && o.preset_time > today && o.state === "draft",
        ).length;
    }
    async cashMove() {
        const moveMade = await this.pos.cashMove();
        if (!moveMade) {
            return;
        }
        this.dialog.closeAll();
        this.pos.closeSession();
    }
    getInitialState() {
        const initialState = { notes: "", payments: {} };
        if (this.pos.config.cash_control) {
            initialState.payments[this.props.default_cash_details.id] = {
                counted: "0",
            };
        }
        this.props.non_cash_payment_methods.forEach((pm) => {
            if (pm.type === "bank") {
                initialState.payments[pm.id] = {
                    counted: this.env.utils.formatCurrency(pm.amount, false),
                };
            }
        });
        return initialState;
    }
    async confirm() {
        const noDifference =
            !this.pos.config.cash_control ||
            this.pos.currency.isZero(this.getMaxDifference());
        log.logic("[session:close] confirm", () => ({
            session: this.pos.session?.id,
            cashControl: this.pos.config.cash_control,
            maxDifference: this.getMaxDifference(),
            noDifference,
            hasUserAuthority: this.hasUserAuthority(),
        }));
        if (noDifference) {
            await this.closeSession();
            return;
        }
        if (this.hasUserAuthority()) {
            const response = await ask(this.dialog, {
                title: _t("Payments Difference"),
                body: _t(
                    "The money counted doesn't match what we expected. Want to log the difference for the books?",
                ),
                confirmLabel: _t("Proceed Anyway"),
                cancelLabel: _t("Discard"),
            });
            log.logic("[session:close] difference acknowledged", () => ({
                proceed: Boolean(response),
            }));
            if (response) {
                return this.closeSession();
            }
            return;
        }
        this.dialog.add(ConfirmationDialog, {
            title: _t("Payments Difference"),
            body: _t(
                "The maximum difference allowed is %s.\nPlease contact your manager to accept the closing difference.",
                this.env.utils.formatCurrency(this.props.amount_authorized_diff),
            ),
        });
    }
    async cancel() {
        if (this.canCancel()) {
            this.props.close();
        }
    }
    canConfirm() {
        return Object.values(this.state.payments)
            .map((v) => v.counted)
            .every(this.env.utils.isValidFloat);
    }
    async openDetailsPopup() {
        const action = _t("Cash control - closing");
        this.hardwareProxy.openCashbox(action);
        this.dialog.add(MoneyDetailsPopup, {
            moneyDetails: this.moneyDetails,
            action: action,
            getPayload: (payload) => {
                const { total, moneyDetailsNotes, moneyDetails } = payload;
                this.state.payments[this.props.default_cash_details.id].counted =
                    this.env.utils.formatCurrency(total, false);
                if (moneyDetailsNotes) {
                    this.state.notes = moneyDetailsNotes;
                }
                this.moneyDetails = moneyDetails;
            },
            context: "Closing",
        });
    }
    async downloadSalesReport() {
        return this.report.doAction("point_of_sale.sale_details_report", [
            this.pos.session.id,
        ]);
    }
    setManualCashInput(amount) {
        if (this.env.utils.isValidFloat(amount) && this.moneyDetails) {
            this.state.notes = "";
            this.moneyDetails = null;
        }
    }
    getDifference(paymentId) {
        const counted = this.state.payments[paymentId].counted;
        if (!this.env.utils.isValidFloat(counted)) {
            return NaN;
        }
        const expectedAmount =
            paymentId === this.props.default_cash_details?.id
                ? this.props.default_cash_details.amount
                : this.props.non_cash_payment_methods.find((pm) => pm.id === paymentId)
                      .amount;

        return parseFloat(counted) - expectedAmount;
    }

    getMaxDifference() {
        return Math.max(
            ...Object.keys(this.state.payments).map((id) =>
                Math.abs(this.getDifference(parseInt(id))),
            ),
        );
    }
    hasUserAuthority() {
        return this.props.is_manager || this.allowedDifference();
    }
    allowedDifference() {
        return (
            this.props.amount_authorized_diff == null ||
            this.getMaxDifference() <= this.props.amount_authorized_diff
        );
    }
    canCancel() {
        return true;
    }
    async closeSession() {
        const endClose = log.perf("[session:close] closeSession");
        this.pos._resetConnectedCashier();
        const syncSuccess = await this.pos.pushOrdersWithClosingPopup();
        log.pipeline("[session:close] orders pushed", () => ({
            session: this.pos.session.id,
            syncSuccess,
        }));
        if (!syncSuccess) {
            endClose({ stoppedAt: "sync" });
            return;
        }
        if (this.pos.config.cash_control) {
            const countedCash = parseFloat(
                this.state.payments[this.props.default_cash_details.id].counted,
            );
            const response = await this.pos.data.call(
                "pos.session",
                "update_closing_cash_details",
                [this.pos.session.id],
                {
                    counted_cash: countedCash,
                },
            );
            log.pipeline("[session:close] cash details", () => ({
                session: this.pos.session.id,
                countedCash,
                expected: this.props.default_cash_details.amount,
                successful: response.successful,
            }));

            if (!response.successful) {
                endClose({ stoppedAt: "cashDetails" });
                return this.handleClosingError(response);
            }
        }

        try {
            await this.pos.data.call(
                "pos.session",
                "update_closing_control_state_session",
                [this.pos.session.id, this.state.notes],
            );
        } catch (error) {
            log.logic("[session:close] closing control state", () => ({
                session: this.pos.session.id,
                alreadyClosed:
                    error.data?.message === "This session is already closed.",
            }));
            if (
                !error.data ||
                error.data.message !== "This session is already closed."
            ) {
                endClose({ stoppedAt: "closingControlState", error: error?.message });
                throw error;
            }
        }

        try {
            const bankPaymentMethodDiffPairs = this.props.non_cash_payment_methods
                .filter((pm) => pm.type === "bank")
                .map((pm) => [pm.id, this.getDifference(pm.id)]);
            log.pipeline("[session:close] close_session_from_ui", () => ({
                session: this.pos.session.id,
                bankDiffs: bankPaymentMethodDiffPairs,
            }));
            const response = await this.pos.data.call(
                "pos.session",
                "close_session_from_ui",
                [this.pos.session.id, bankPaymentMethodDiffPairs],
                {
                    context: {
                        device_identifier: this.pos.device.identifier,
                    },
                },
            );
            if (!response.successful) {
                endClose({
                    stoppedAt: "closeSessionFromUi",
                    redirect: response.redirect,
                });
                return this.handleClosingError(response);
            }
            log.lifecycle("[session:close] closed", () => ({
                session: this.pos.session.id,
            }));
            this.pos.session.state = "closed";
            endClose({ closed: true });
            this.pos.router.close();
        } catch (error) {
            endClose({
                stoppedAt: "closeSessionFromUi",
                connectionLost: error instanceof ConnectionLostError,
                error: error?.message,
            });
            if (error instanceof ConnectionLostError) {
                throw error;
            } else {
                await this.handleClosingControlError();
            }
        } finally {
            localStorage.removeItem(`pos.session.${odoo.pos_config_id}`);
        }
    }
    async handleClosingControlError() {
        this.dialog.add(
            AlertDialog,
            {
                title: _t("Closing session error"),
                body: _t(
                    "An error has occurred when trying to close the session.\n" +
                        "You will be redirected to the back-end to manually close the session.",
                ),
            },
            {
                onClose: () => {
                    this.dialog.add(
                        FormViewDialog,
                        {
                            resModel: "pos.session",
                            resId: this.pos.session.id,
                        },
                        {
                            onClose: async () => {
                                const session = await this.pos.data.read(
                                    "pos.session",
                                    [this.pos.session.id],
                                );
                                if (session[0] && session[0].state === "closed") {
                                    this.pos.router.close();
                                } else {
                                    this.pos.redirectToBackend();
                                }
                            },
                        },
                    );
                },
            },
        );
    }
    async handleClosingError(response) {
        log.logic("[session:close] handleClosingError", () => ({
            title: response.title,
            redirect: response.redirect,
            openOrders: response.open_order_ids?.length,
        }));
        this.dialog.add(ConfirmationDialog, {
            title: response.title || "Error",
            body: response.message,
            confirmLabel: _t("Review Orders"),
            cancelLabel: _t("Cancel Orders"),
            confirm: () => {
                if (!response.redirect) {
                    this.props.close();
                    this.pos.navigate("TicketScreen");
                }
            },
            cancel: async () => {
                if (!response.redirect) {
                    const now = DateTime.now();
                    const ordersDraft = this.pos.models["pos.order"].filter(
                        (o) => !o.finalized && !(o.preset_time && o.preset_time > now),
                    );
                    log.pipeline("[session:close] cancel open orders", () => ({
                        drafts: ordersDraft.map((o) => o.uuid),
                        serverIds: response.open_order_ids,
                    }));
                    await this.pos.removeOrders(ordersDraft, response.open_order_ids);
                    this.closeSession();
                }
            },
            dismiss: async () => {},
        });

        if (response.redirect) {
            this.pos.router.close();
        }
    }
    getMovesTotalAmount() {
        const amounts = this.props.default_cash_details.moves.map(
            (move) => move.amount,
        );
        return amounts.reduce((acc, x) => acc + x, 0);
    }
}
