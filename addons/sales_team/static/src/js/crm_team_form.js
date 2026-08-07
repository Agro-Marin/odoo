/** @odoo-module native */

import { _t } from "@web/core/translation";
import { formView, FormController } from "@web/views/form";
import { registry } from "@web/core/registry";

/**
 * Controller used to directly activate the multi-team option
 * via a button present in the crm team member alert.
 *
 * This alert is only displayed when a user is assigned to
 * multiple teams but the multi-team option is deactivated.
 */
class CrmTeamFormController extends FormController {

    async beforeExecuteActionButton(clickParams) {
        if (clickParams.name !== "crm_team_activate_multi_membership") {
            return super.beforeExecuteActionButton(...arguments);
        }
        try {
            // the group check lives on the model: `user.hasGroup` is async, so
            // guarding on it here silently passed everyone, and the parameter
            // write it guarded needs Settings rights the Sales Administrators
            // reading this banner do not have
            await this.orm.call("crm.team", "action_activate_multi_membership", []);
        } catch {
            this.notification.add(
                _t("An error occurred while activating the Multi-Team option."),
                { type: "danger" },
            );
            return false;
        }
        // reload so `is_membership_multi` recomputes and the banner disappears on
        // its own -- hiding the alert by hand left the record stale and the class
        // was dropped by the next render anyway
        await this.model.root.load();
        return false;
    }
}

registry.category("views").add("crm_team_form", {
    ...formView,
    Controller: CrmTeamFormController,
});
