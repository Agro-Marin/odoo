/** @odoo-module native */
import { LivechatButton } from "@im_livechat/embed/common/livechat_button";
import { ChatHub } from "@mail/core/common/chat_hub";
import { useListener } from "@web/core/utils/owl_bridge";
import { patch } from "@web/core/utils/patch";

ChatHub.components = { ...ChatHub.components, LivechatButton };

patch(ChatHub.prototype, {
    setup() {
        super.setup(...arguments);
        useListener(document, "scroll", this._onScroll.bind(this));
    },
    _onScroll(ev) {
        if (this.position.dragged) {
            return;
        }
        const container = document.querySelector("html");
        this.position.bottom =
            container.scrollHeight - container.scrollTop === container.clientHeight
                ? `${this.chatHub.BUBBLE_OUTER * 5}px`
                : `${this.chatHub.BUBBLE_OUTER}px`;
    },
});
