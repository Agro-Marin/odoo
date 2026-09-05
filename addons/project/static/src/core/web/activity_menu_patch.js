/** @odoo-module native */
import { ActivityMenu } from "@mail/core/web/activity_menu";
import { patch } from "@web/core/utils/patch";

patch(ActivityMenu.prototype, {
    /**
     * The systray counts activities on sub-tasks too, so the list opened from
     * it must show them whatever the user's "Show Sub-Tasks" preference is,
     * or the count and the list disagree.
     */
    executeActivityAction(group, domain, views, context, newWindow) {
        if (group.model === "project.task") {
            context.activity_action = true;
        }
        return super.executeActivityAction(...arguments);
    },
});
