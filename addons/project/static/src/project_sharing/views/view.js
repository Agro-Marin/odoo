/** @odoo-module native */
import { router } from "@web/core/browser/router";
import { patch } from "@web/core/utils/patch";
import { session } from "@web/session";
import { View } from "@web/views/view";

patch(View.prototype, {
    setup() {
        super.setup();
        if (
            router.current.action === "project_sharing" &&
            !router.current.resId &&
            router.current.active_id === session.project_id
        ) {
            this.env.config.setDisplayName(session.project_name);
        }
    },
});
