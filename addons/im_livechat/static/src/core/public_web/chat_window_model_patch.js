/** @odoo-module native */
import { ChatWindow } from "@mail/core/common/chat_window_model";
import { patch } from "@web/core/utils/patch";

patch(ChatWindow.prototype, {
    _onClose(options = {}) {
        if (
            this.thread?.isLivechat &&
            this.thread.livechatVisitorMember?.persona?.notEq(this.store.self)
        ) {
            const thread = this.thread;
            super._onClose(...arguments);
            this.delete();
            if (options.notifyState) {
                thread.leaveChannel({ force: true });
            }
        } else {
            super._onClose(...arguments);
        }
    },
});
