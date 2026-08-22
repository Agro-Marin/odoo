/** @odoo-module native */
import { MessagingMenu } from "@mail/core/common/messaging_menu_model";
import { patch } from "@web/core/utils/patch";

/** @type {import("models").MessagingMenu} */
const messagingMenuPatch = {
    /**
     * @override
     */
    tabToThreadType(tab) {
        const threadTypes = super.tabToThreadType(tab);
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
