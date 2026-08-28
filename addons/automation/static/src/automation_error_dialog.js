/** @odoo-module native */
import { RPCErrorDialog } from "@web/components/errors";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { user } from "@web/core/user";

export class AutomationErrorDialog extends RPCErrorDialog {
    static template = "automation.ErrorDialog";
    setup() {
        super.setup(...arguments);
        const { id, name } = this.props.data.context.automation;
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
        await this.orm.write("automation.rule", [this.automationId], { active: false });
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
            res_model: "automation.rule",
            res_id: this.automationId,
            views: [[false, "form"]],
            type: "ir.actions.act_window",
            view_mode: "form",
            target: "new",
        });
        this.props.close();
    }
}

registry.category("error_dialogs").add("automation", AutomationErrorDialog);
