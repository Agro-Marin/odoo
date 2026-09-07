/** @odoo-module native */
import { Component } from "@odoo/owl";
import { Dialog } from "@web/ui/dialog";
import { deserializeDate, formatDate } from "@web/core/l10n/dates";

export class PortalLoyaltyCardDialog extends Component {
    static components = { Dialog };
    static template = "loyalty.portal_loyalty_card_dialog";
    static props = ["*"];

    get formattedExpirationDate() {
        return formatDate(deserializeDate(this.props.card.expiration_date));
    }
}
