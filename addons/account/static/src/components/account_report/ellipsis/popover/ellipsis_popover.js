/** @odoo-module native */
import { Component } from "@odoo/owl";

export class AccountReportEllipsisPopover extends Component {
    static template = "account.AccountReportEllipsisPopover";
    static props = {
        close: Function,
        name: String,
        copyEllipsisText: Function,
    };
}
