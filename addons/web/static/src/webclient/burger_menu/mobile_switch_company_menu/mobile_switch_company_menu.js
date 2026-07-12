// @ts-check
/** @odoo-module native */

/** @module @web/webclient/burger_menu/mobile_switch_company_menu/mobile_switch_company_menu - Mobile company switcher with collapsible toggle for many companies */

import { onWillUnmount } from "@odoo/owl";
import { SwitchCompanyMenu } from "@web/webclient/switch_company_menu/switch_company_menu";

export class MobileSwitchCompanyMenu extends SwitchCompanyMenu {
    static template = "web.MobileSwitchCompanyMenu";

    setup() {
        super.setup();
        /** @type {any} */ (this.state).isOpen = false;
        // The desktop switcher discards its draft selection when the dropdown
        // closes (see SwitchCompanyMenu.handleDropdownChange). The mobile
        // switcher has no dropdown; it lives inside the burger menu, which
        // unmounts it on close. Reset the draft on unmount so unconfirmed
        // toggles can't be applied by a later Confirm after the burger reopens.
        onWillUnmount(() => this.companySelector.reset());
    }

    /** @returns {boolean} whether the company list should be visible */
    get show() {
        return (
            !this.hasLotsOfCompanies || /** @type {any} */ (this.state).isOpen === true
        );
    }

    /** Toggle the company list visibility when many companies exist. */
    toggleCollapsible() {
        if (this.hasLotsOfCompanies) {
            const willOpen = !(/** @type {any} */ (this.state).isOpen);
            /** @type {any} */ (this.state).isOpen = willOpen;
            if (!willOpen) {
                // Collapsing the list is the mobile analog of closing the
                // desktop dropdown: discard the draft selection so pending
                // toggles cannot be applied by a later Confirm.
                this.companySelector.reset();
            }
        }
    }
}
