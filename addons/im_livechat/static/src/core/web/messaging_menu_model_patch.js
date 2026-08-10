/** @odoo-module native */
import { MessagingMenu } from "@mail/core/common/messaging_menu_model";
import { patch } from "@web/core/utils/patch";

/** @type {import("models").MessagingMenu} */
const messagingMenuPatch = {
    /**
     * Livechat conversations show under their own tab, and — on a wide screen
     * only, where the extra tab has room — also under "chat".
     *
     * @override
     */
    tabToThreadType(tab) {
        const threadTypes = super.tabToThreadType(tab);
        // A record is not the Store, so `env` comes through it. Only the Store
        // record is given an `env` of its own by `Record.new`.
        if (tab === "chat" && !this.store.env.services.ui.isSmall) {
            threadTypes.push("livechat");
        }
        if (tab === "livechat") {
            threadTypes.push("livechat");
        }
        return threadTypes;
    },
};

patch(MessagingMenu.prototype, messagingMenuPatch);
