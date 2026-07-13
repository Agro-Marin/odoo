/** @odoo-module native */
import { registerThreadAction } from "@mail/core/common/thread_actions";
import { _t } from "@web/core/l10n/translation";

registerThreadAction("open-hr-profile", {
    condition: ({ owner, thread }) =>
        thread?.channel_type === "chat" &&
        owner.props.chatWindow?.isOpen &&
        thread.correspondent?.partner_id?.employeeId &&
        !owner.isDiscussSidebarChannelActions,
    icon: "fa-solid fa-id-card",
    name: _t("Open Profile"),
    open: async ({ store, thread }) =>
        store.env.services.action.doAction({
            type: "ir.actions.act_window",
            res_id: thread.correspondent.partner_id?.employeeId,
            res_model: "hr.employee.public",
            views: [[false, "form"]],
        }),
    async setup({ thread }) {
        let employeeId;
        if (thread?.correspondent?.partner_id && !thread.correspondent.partner_id.employeeId) {
            const employees = await this.store.env.services.orm.silent.searchRead(
                // Regular internal users can only read hr.employee.public (the
                // `open` handler and store_service_patch already use it); querying
                // hr.employee here would raise AccessError for non-HR users.
                "hr.employee.public",
                [["user_partner_id", "=", thread.correspondent.partner_id.id]],
                ["id"]
            );
            employeeId = employees[0]?.id;
            if (employeeId) {
                thread.correspondent.partner_id.employeeId = employeeId;
            }
        }
    },
    sequence: 16,
});
