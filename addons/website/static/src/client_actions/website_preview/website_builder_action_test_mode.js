/** @odoo-module native */
import { patch } from "@web/core/utils/patch";

import { WebsiteBuilderClientAction } from "./website_builder_action.js";

patch(WebsiteBuilderClientAction.prototype, {
    /**
     * @override
     */
    get testMode() {
        return true;
    },
});
