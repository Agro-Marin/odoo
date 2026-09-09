/** @odoo-module native */
import { Component, useState } from "@odoo/owl";
import { Dropdown, DropdownItem } from "@web/components/dropdown";

export class AccountReportCogMenu extends Component {
    static template = "account.AccountReportCogMenu";
    static components = { Dropdown, DropdownItem };
    static props = {};

    setup() {
        this.controller = useState(this.env.controller);
    }

    //------------------------------------------------------------------------------------------------------------------
    // Buttons
    //------------------------------------------------------------------------------------------------------------------
    get cogButtons() {
        const buttons = [];

        for (const button of this.controller.buttons) {
            if (!button.always_show) {
                buttons.push({
                    ...button,
                    onClick: (ev) => this.controller.buttonAction(ev, button),
                });
            }
        }

        return buttons;
    }
}
