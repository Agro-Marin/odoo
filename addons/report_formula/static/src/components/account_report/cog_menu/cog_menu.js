/** @odoo-module native */
import { Component, useState } from "@odoo/owl";
import { Dropdown } from "@web/components/dropdown";
import { COG_GROUP } from "@web/search/cog_menu/cog_menu_group";
import { CogMenuItem } from "@web/search/cog_menu/cog_menu_item";
import { useService } from "@web/core/utils/hooks";
import { useAccountReportContext } from "@report_formula/components/account_report/account_report_context";

export class AccountReportCogMenu extends Component {
    static template = "report_formula.AccountReportCogMenu";
    static components = { CogMenuItem, Dropdown };
    static props = {};

    setup() {
        this.reportContext = useAccountReportContext();
        this.ui = useService("ui");
        this.controller = useState(this.reportContext.controller);
    }

    //------------------------------------------------------------------------------------------------------------------
    // Buttons
    //------------------------------------------------------------------------------------------------------------------
    get cogButtons() {
        const buttons = [];

        for (const button of this.controller.buttons) {
            if (!button.always_show) {
                buttons.push({
                    groupNumber: COG_GROUP.APP,
                    ...button,
                    onClick: (ev) => this.controller.buttonAction(ev, button),
                });
            }
        }

        return buttons;
    }
}
