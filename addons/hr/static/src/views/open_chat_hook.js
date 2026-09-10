/** @odoo-module native */
import { helpers } from "@mail/core/web/open_chat_hook";
import { patch } from "@web/core/utils/patch";

patch(helpers, {
    SUPPORTED_M2X_AVATAR_MODELS: [
        ...helpers.SUPPORTED_M2X_AVATAR_MODELS,
        "hr.employee",
    ],
    prepareOpenChatParams(resModel, id) {
        if (resModel === "hr.employee") {
            return { employeeId: id };
        }
        return super.prepareOpenChatParams(...arguments);
    },
});
