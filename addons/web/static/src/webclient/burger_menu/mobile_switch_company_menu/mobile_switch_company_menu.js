// @ts-check
/** @odoo-module native */

import { onWillUnmount } from "@odoo/owl";
import { SwitchCompanyMenu } from "@web/webclient/switch_company_menu/switch_company_menu";

export class MobileSwitchCompanyMenu extends SwitchCompanyMenu {
    static template = "web.MobileSwitchCompanyMenu";

    setup() {
        super.setup();
        /** @type {any} */ (this.state).isOpen = false;
        onWillUnmount(() => this.companySelector.reset());
    }

    /** @returns {boolean} */
    get show() {
        return (
            !this.hasLotsOfCompanies || /** @type {any} */ (this.state).isOpen === true
        );
    }

    toggleCollapsible() {
        if (this.hasLotsOfCompanies) {
            const willOpen = !(/** @type {any} */ (this.state).isOpen);
            /** @type {any} */ (this.state).isOpen = willOpen;
            if (!willOpen) {
                this.companySelector.reset();
            }
        }
    }
}
