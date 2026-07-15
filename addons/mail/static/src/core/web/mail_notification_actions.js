/** @odoo-module native */
import { registry } from "@web/core/registry";

registry.category("actions").add("action_send_mail_callback", async (env, action) => {
    const store = env.services["mail.store"];
    const discuss = store.discuss;
    if (discuss.isActive && discuss.thread?.isMailbox) {
        store.notifySendFromMailbox(action.params.record_name);
    }
    await env.services.action.doAction({ type: "ir.actions.act_window_close" });
});
