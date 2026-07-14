/** @odoo-module native */
import { ActionPanel } from "@mail/core/common/action_panel";
import { patch } from "@web/core/utils/patch";
patch(ActionPanel.prototype, {
    get initialWidth() {
        return super.initialWidth || this.store.discuss.INSPECTOR_WIDTH;
    },
    get minWidth() {
        return super.minWidth || this.store.discuss.INSPECTOR_WIDTH;
    },
});
