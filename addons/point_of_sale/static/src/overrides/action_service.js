/** @odoo-module native */
import { patch } from "@web/core/utils/patch";
import { ActionManager } from "@web/webclient/actions";

patch(ActionManager.prototype, {
    doAction(actionRequest, options = {}) {
        if (
            document.body.classList.contains("modal-open") &&
            typeof actionRequest === "object"
        ) {
            actionRequest.target = "new";
        }
        return super.doAction(actionRequest, options);
    },
});
