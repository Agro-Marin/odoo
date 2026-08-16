/** @odoo-module native */
import { patch } from "@web/core/utils/patch";
import { Dialog } from "@web/ui/dialog";
patch(Dialog.prototype, {
    onEscape() {
        const messageModels = ["mail.compose.message", "mail.scheduled.message"];
        if (messageModels.includes(this.data.model)) {
            return;
        }
        super.onEscape();
    },
});
