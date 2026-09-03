/** @odoo-module native */
import { Component } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { url } from "@web/core/utils/urls";
export class MessageInReply extends Component {
    static props = ["class?", "message", "onClick?"];
    static defaultProps = { class: "" };
    static template = "mail.MessageInReply";

    setup() {
        super.setup();
        this.store = useService("mail.store");
    }

    get authorAvatarUrl() {
        const parent = this.props.message.parent_id;
        if (
            parent.message_type &&
            parent.message_type.includes("email") &&
            !parent.author_id &&
            !parent.author_guest_id
        ) {
            return url("/mail/static/src/img/email_icon.png");
        }
        return parent.author?.avatarUrl ?? this.store.DEFAULT_AVATAR;
    }
}
