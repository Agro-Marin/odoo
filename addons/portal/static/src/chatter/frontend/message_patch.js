/** @odoo-module native */
import { Message } from "@mail/core/common/message";
import { useMailContext } from "@mail/utils/common/mail_context";
import { patch } from "@web/core/utils/patch";

const PORTAL_AVATAR_SIZE = "50x50";

patch(Message.prototype, {
    setup() {
        super.setup(...arguments);
        this.mailContext = useMailContext();
    },

    get authorAvatarUrl() {
        if (this.message.author_avatar_url) {
            return this.message.author_avatar_url;
        }
        if (this.message.thread.access_token) {
            return `/mail/avatar/mail.message/${this.message.id}/author_avatar/${PORTAL_AVATAR_SIZE}?access_token=${this.message.thread.access_token}`;
        }
        return super.authorAvatarUrl;
    },

    get shouldHideFromMessageListOnDelete() {
        return (
            this.mailContext.inFrontendPortalChatter ||
            super.shouldHideFromMessageListOnDelete
        );
    },
});
