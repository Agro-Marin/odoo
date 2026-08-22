// @ts-check
/** @odoo-module native */

import { Component, useState } from "@odoo/owl";
import { DropdownItem } from "@web/components/dropdown/dropdown_item";
import { _t } from "@web/core/translation";
import { user } from "@web/core/user";
import { isCompanyAllowed } from "@web/webclient/switch_company_menu/company_selector";

export class SwitchCompanyItem extends Component {
    static template = "web.SwitchCompanyItem";
    static components = { DropdownItem, SwitchCompanyItem };
    static props = {
        company: {},
        level: { type: Number },
    };

    setup() {
        this.companySelector = useState(this.env.companySelector);
    }

    /** @returns {boolean} */
    get isCompanySelected() {
        return this.companySelector.isCompanySelected(this.props.company.id);
    }

    /** @returns {boolean} */
    get isCompanyAllowed() {
        return isCompanyAllowed(this.props.company.id);
    }

    /** @returns {boolean} */
    get isCurrent() {
        return this.props.company.id === user.activeCompany.id;
    }

    /** @returns {string} */
    get toggleTitle() {
        return this.isCompanySelected
            ? _t("Hide %s content.", this.props.company.name)
            : _t("Show %s content.", this.props.company.name);
    }

    /** @returns {string} */
    get logIntoTitle() {
        return _t("Switch to %s", this.props.company.name);
    }

    logIntoCompany() {
        if (this.isCompanyAllowed) {
            this.companySelector.switchCompany("loginto", this.props.company.id);
        }
    }

    toggleCompany() {
        if (this.isCompanyAllowed) {
            this.companySelector.switchCompany("toggle", this.props.company.id);
        }
    }
}
