/** @odoo-module native */
import { Component } from "@odoo/owl";
import { Dialog } from "@web/ui/dialog";

export class PortalLoyaltyCardDialog extends Component {
    static components = { Dialog };
    static template = "loyalty.portal_loyalty_card_dialog";
    static props = ["*"];
}
