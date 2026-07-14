/** @odoo-module native */
import { ChatWindow } from "@mail/core/common/chat_window";
import { Typing } from "@mail/discuss/typing/common/typing";
import { patch } from "@web/core/utils/patch";
patch(ChatWindow, {
    components: { ...ChatWindow.components, Typing },
});
