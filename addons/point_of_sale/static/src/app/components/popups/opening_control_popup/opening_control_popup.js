/** @odoo-module native */
import { Component, useState } from "@odoo/owl";
import { Input } from "@point_of_sale/app/components/inputs/input/input";
import { MoneyDetailsPopup } from "@point_of_sale/app/components/popups/money_details_popup/money_details_popup";
import { usePos } from "@point_of_sale/app/hooks/pos_hook";
import { makeLogger } from "@web/core/debug/debug_logger";
import { useLifecycleLog } from "@web/core/debug/logger_hooks";
import { RPCError } from "@web/core/network";
import { parseFloat } from "@web/core/parsers";
import { _t } from "@web/core/translation";
import { useService } from "@web/core/utils/hooks";
import { Dialog } from "@web/ui/dialog";
const log = makeLogger("pos.popup.opening");
class CustomDialog extends Dialog {
    onEscape() {}
}

export class OpeningControlPopup extends Component {
    static template = "point_of_sale.OpeningControlPopup";
    static components = { Input, Dialog: CustomDialog };
    static props = {
        close: Function,
    };

    setup() {
        useLifecycleLog(log);
        this.moneyDetails = null;
        this.pos = usePos();
        this.dialog = useService("dialog");
        log.lifecycle("[session:open] opened", () => ({
            session: this.pos.session.id,
            state: this.pos.session.state,
            balanceStart: this.pos.session.cash_register_balance_start,
            cashMethods: this.cashMethodCount,
            draftOrders: this.orderCount,
        }));
        this.state = useState({
            notes: "",
            openingCash: this.env.utils.formatCurrency(
                this.pos.session.cash_register_balance_start || 0,
                false,
            ),
        });
        this.hardwareProxy = useService("hardware_proxy");
        this.ui = useService("ui");
    }
    get orderCount() {
        return this.pos.models["pos.order"].filter(
            (o) => o.lines.length > 0 && o.state === "draft",
        ).length;
    }
    async confirm() {
        const endOpen = log.perf("[session:open] set_opening_control");
        log.pipeline("[session:open] confirm", () => ({
            session: this.pos.session.id,
            openingCash: this.state.openingCash,
            notes: Boolean(this.state.notes),
        }));
        try {
            await this.pos.data.call(
                "pos.session",
                "set_opening_control",
                [
                    this.pos.session.id,
                    parseFloat(this.state.openingCash),
                    this.state.notes,
                ],
                {},
                true,
            );
        } catch (error) {
            endOpen({ session: this.pos.session.id, error: error?.message });
            if (
                error instanceof RPCError &&
                error.data.name === "odoo.exceptions.MissingError" &&
                (await this.pos.isSessionDeleted())
            ) {
                log.logic("[session:open] session deleted, reloading", () => ({
                    session: this.pos.session.id,
                }));
                return window.location.reload();
            }
            throw error;
        }
        endOpen({ session: this.pos.session.id });
        log.lifecycle("[session:open] state -> opened", () => ({
            session: this.pos.session.id,
        }));
        this.pos.session.state = "opened";
        this.props.close();
    }
    async openDetailsPopup() {
        const action = _t("Cash control - opening");
        this.hardwareProxy.openCashbox(action);
        this.dialog.add(MoneyDetailsPopup, {
            moneyDetails: this.moneyDetails,
            action: action,
            getPayload: (payload) => {
                if (payload) {
                    const { total, moneyDetails, moneyDetailsNotes } = payload;
                    this.state.openingCash = this.env.utils.formatCurrency(
                        total,
                        false,
                    );
                    if (moneyDetailsNotes) {
                        this.state.notes = moneyDetailsNotes;
                    }
                    this.moneyDetails = moneyDetails;
                }
            },
            context: "Opening",
        });
    }
    handleInputChange() {
        if (!this.env.utils.isValidFloat(this.state.openingCash)) {
            return;
        }
        this.state.notes = "";
    }
    get cashMethodCount() {
        return this.pos.config.payment_method_ids.filter((pm) => pm.is_cash_count)
            .length;
    }
}
