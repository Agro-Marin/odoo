/** @odoo-module native */
import { ChatWindow } from "@mail/core/common/chat_window_model";
import { patch } from "@web/core/utils/patch";
patch(ChatWindow.prototype, {
    /** @param {Object} [options] */
    async _onClose(options) {
        if (
            this.store.env.services.ui.isSmall &&
            !this.store.discuss.isActive &&
            this.fromMessagingMenu
        ) {
            this.store.messagingMenu.dropdown?.open();
            await Promise.resolve();
        }
        await super._onClose(...arguments);
    },
});
