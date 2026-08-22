/** @odoo-module native */
import { useOpenChat } from "@mail/core/web/open_chat_hook";
import { TagsList } from "@web/components/tags_list";
import { patch } from "@web/core/utils/patch";
import { PropertyValue } from "@web/fields/specialized/properties";
patch(PropertyValue.prototype, {
    setup() {
        super.setup();

        if (this.env.services["mail.store"]) {
            this.openChat = useOpenChat("res.users");
        }
    },

    _onAvatarClicked() {
        if (this.openChat && this.showAvatar && this.props.comodel === "res.users") {
            this.openChat(this.props.value.id);
        }
    },
});

export class Many2manyPropertiesTagsList extends TagsList {
    static template = "mail.Many2manyPropertiesTagsList";

    setup() {
        super.setup();
        if (this.env.services["mail.store"]) {
            this.openChat = useOpenChat("res.users");
        }
    }

    /** @param {number} tagIndex */
    _onAvatarClicked(tagIndex) {
        const tag = this.props.tags[tagIndex];
        if (this.openChat && tag.comodel === "res.users") {
            this.openChat(tag.id);
        }
    }
}

PropertyValue.components = {
    ...PropertyValue.components,
    TagsList: Many2manyPropertiesTagsList,
};
