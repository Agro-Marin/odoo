/** @odoo-module */
import { patch } from "@web/core/utils/patch";
import { WebsiteBuilderClientAction } from "@website/client_actions/website_preview/website_builder_action";

patch(WebsiteBuilderClientAction.prototype, {
    /**
     * @override
     */
    get testMode() {
        return true;
    },
});
