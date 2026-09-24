/** @odoo-module native */
import { Component, useState } from "@odoo/owl";
import { useAccountReportContext } from "@report_formula/components/account_report/account_report_context";

export class AccountReportButtonsBar extends Component {
    static template = "report_formula.AccountReportButtonsBar";
    static props = {};

    setup() {
        this.reportContext = useAccountReportContext();
        this.controller = useState(this.reportContext.controller);
    }

    //------------------------------------------------------------------------------------------------------------------
    // Buttons
    //------------------------------------------------------------------------------------------------------------------
    get barButtons() {
        const buttons = [];

        for (const button of this.controller.buttons) {
            if (button.always_show) {
                buttons.push(button);
            }
        }

        return buttons;
    }
}
