/** @odoo-module native */
import { patch } from "@web/core/utils/patch";
import { Dialog } from "@web/ui/dialog/dialog";
patch(Dialog.prototype, {
    /**
     * @override
     */
    onEscape() {
        const messageModels = ["mail.compose.message", "mail.scheduled.message"];
        if (messageModels.includes(this.data.model)) {
            return;
        }
        super.onEscape();
    },
});
