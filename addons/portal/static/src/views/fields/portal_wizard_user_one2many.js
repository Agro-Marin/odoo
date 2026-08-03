/** @odoo-module native */
import { registry } from "@web/core/registry";
import { X2ManyField, x2ManyField } from "@web/fields/relational/x2many";

import { PortalWizardUserListController } from "../list/portal_wizard_user_list_controller.js";

export class PortalUserX2ManyField extends X2ManyField {
    static components = {
        ...X2ManyField.components,
        Controller: PortalWizardUserListController,
    };
}

export const portalUserX2ManyField = {
    ...x2ManyField,
    component: PortalUserX2ManyField,
};

registry.category("fields").add("portal_wizard_user_one2many", portalUserX2ManyField);
