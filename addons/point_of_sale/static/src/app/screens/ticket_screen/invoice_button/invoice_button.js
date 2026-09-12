/** @odoo-module native */
import { Component } from "@odoo/owl";
import { usePos } from "@point_of_sale/app/hooks/pos_hook";
import { ask, makeAwaitable } from "@point_of_sale/app/utils/make_awaitable_dialog";
import { makeLogger } from "@web/core/debug/debug_logger";
import { _t } from "@web/core/translation";
import { useService } from "@web/core/utils/hooks";
import { AlertDialog } from "@web/ui/dialog";

import { PartnerList } from "../../partner_list/partner_list.js";
const log = makeLogger("pos.screen.ticket.invoice");

export class InvoiceButton extends Component {
    static template = "point_of_sale.InvoiceButton";
    static props = {
        order: Object,
        onInvoiceOrder: Function,
    };

    setup() {
        this.pos = usePos();
        this.dialog = useService("dialog");
        this.invoiceService = useService("account_move");
        this.lock = false;
    }
    get isAlreadyInvoiced() {
        if (!this.props.order) {
            return false;
        }
        return Boolean(this.props.order.raw.account_move);
    }
    get commandName() {
        if (!this.props.order) {
            return _t("Invoice");
        } else {
            return this.isAlreadyInvoiced ? _t("Reprint Invoice") : _t("Invoice");
        }
    }
    async _downloadInvoice(orderId) {
        const endDownload = log.perf("downloadInvoice");
        try {
            const orders = await this.pos.data.loadServerOrders([["id", "=", orderId]]);
            const order = orders[0];
            const accountMoveId = order.raw.account_move;
            log.pipeline("downloadInvoice", () => ({
                order: order.uuid,
                id: orderId,
                accountMove: accountMoveId,
            }));
            if (accountMoveId) {
                await this.invoiceService.downloadPdf(accountMoveId);
            }
            endDownload({ id: orderId, accountMove: accountMoveId });
        } catch (error) {
            endDownload({ id: orderId, error: error?.message });
            if (error instanceof Error) {
                throw error;
            } else {
                this.dialog.add(AlertDialog, {
                    title: _t("Network Error"),
                    body: _t("Unable to download invoice."),
                    showReloadButton: true,
                });
            }
        }
    }
    async onWillInvoiceOrder(order, partner) {
        return true;
    }
    async _invoiceOrder() {
        const order = this.props.order;
        if (!order) {
            return;
        }

        const orderId = order.id;
        log.logic("invoiceOrder", () => ({
            order: order.uuid,
            id: orderId,
            alreadyInvoiced: this.isAlreadyInvoiced,
            partner: order.getPartner()?.id,
        }));
        if (this.isAlreadyInvoiced) {
            await this._downloadInvoice(orderId);
            this.props.onInvoiceOrder(orderId);
            return;
        }

        let partner = order.getPartner();
        if (!partner) {
            const _confirmed = await ask(this.dialog, {
                title: _t("Need customer to invoice"),
                body: _t("Do you want to open the customer list to select customer?"),
            });
            if (!_confirmed) {
                return;
            }
            partner = await makeAwaitable(this.dialog, PartnerList);
            log.logic("invoiceOrder: partner chosen", () => ({
                order: order.uuid,
                partner: partner?.id,
            }));
            if (!partner) {
                return;
            }

            await this.pos.data.ormWrite("pos.order", [orderId], {
                partner_id: partner.id,
            });
        }

        const confirmed = await this.onWillInvoiceOrder(order, partner);
        if (!confirmed) {
            log.logic("invoiceOrder: onWillInvoiceOrder refused", () => ({
                order: order.uuid,
            }));
            return;
        }

        const endInvoice = log.perf("action_pos_order_invoice");
        await this.pos.data.call("pos.order", "action_pos_order_invoice", [orderId]);
        endInvoice({ order: order.uuid, id: orderId });

        await this._downloadInvoice(orderId);
        this.props.onInvoiceOrder(orderId);
    }
    async click() {
        if (this.lock) {
            return;
        }

        this.lock = true;
        try {
            await this._invoiceOrder();
        } finally {
            this.lock = false;
        }
    }
}
