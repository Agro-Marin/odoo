/** @odoo-module native */
import { ActivityMenu } from "@mail/core/web/activity_menu";

import { patch } from "@web/core/utils/patch";

patch(ActivityMenu.prototype, {
    /**
     * @override This
     */
    async executeActivityAction(group, domain, views, context, newWindow) {
        if (group.model === "document.document") {
            const action = await this.env.services.action.loadAction(
                "document.document_action",
            );

            action.domain = domain;

            return this.action.doAction(action, {
                newWindow,
                clearBreadcrumbs: true,
                viewType: group.view_type,
                additionalContext: context,
            });
        }

        return super.executeActivityAction(...arguments);
    },

    async onClickRequestDocument() {
        this.dropdown.close();
        this.env.services.action.doAction("document.action_request_form");
    },
});
