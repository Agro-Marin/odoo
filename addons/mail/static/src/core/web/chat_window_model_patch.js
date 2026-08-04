/** @odoo-module native */
import { ChatWindow } from "@mail/core/common/chat_window_model";
import { patch } from "@web/core/utils/patch";
patch(ChatWindow.prototype, {
    async _onClose(options) {
        if (
            this.store.env.services.ui.isSmall &&
            !this.store.discuss.isActive &&
            this.fromMessagingMenu
        ) {
            // On mobile with discuss closed, the chat window came from the
            // messaging menu: reopen it to simulate a background menu.
            document.querySelector(".o_menu_systray i[aria-label='Messages']")?.click();
            // ensure messaging menu is opened before chat window is closed
            await Promise.resolve();
        }
        await super._onClose(...arguments);
    },
});
