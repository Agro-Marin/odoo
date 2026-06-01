/** @odoo-module native */
import { Message } from "@mail/core/common/message";

import { patch } from "@web/core/utils/patch";

// Keep in sync with ``_PORTAL_AVATAR_SIZE`` in ``portal/models/mail_message.py``.
// Used by the access-token fallback below when a message arrives client-side
// (e.g. via bus) without ``author_avatar_url`` set by the server formatter.
const PORTAL_AVATAR_SIZE = "50x50";

patch(Message.prototype, {
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
        return this.env.inFrontendPortalChatter || super.shouldHideFromMessageListOnDelete;
    },
});
