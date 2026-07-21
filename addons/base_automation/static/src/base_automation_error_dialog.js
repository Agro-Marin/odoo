/** @odoo-module native */
import { RPCErrorDialog } from "@web/components/errors/error_dialogs";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { user } from "@web/services/user";

export class BaseAutomationErrorDialog extends RPCErrorDialog {
    static template = "base_automation.ErrorDialog";
    setup() {
        super.setup(...arguments);
        const { id, name } = this.props.data.context.base_automation;
        this.automationId = id;
        this.automationName = name;
        this.isUserAdmin = user.isAdmin;
        this.actionService = useService("action");
        this.orm = useService("orm");
    }

    //--------------------------------------------------------------------------
    // Handlers
    //--------------------------------------------------------------------------

    /**
     * Disable the automation rule (set `active` to false).
     *
     * @private
     * @param {MouseEvent} ev
     */
    async disableAutomation(ev) {
        await this.orm.write("base.automation", [this.automationId], { active: false });
        this.props.close();
    }
    /**
     * Open the automation rule form for editing.
     *
     * @private
     * @param {MouseEvent} ev
     */
    editAutomation(ev) {
        this.actionService.doAction({
            name: "Automation Rules",
            res_model: "base.automation",
            res_id: this.automationId,
            views: [[false, "form"]],
            type: "ir.actions.act_window",
            view_mode: "form",
            target: "new",
        });
        this.props.close();
    }
}

registry.category("error_dialogs").add("base_automation", BaseAutomationErrorDialog);
