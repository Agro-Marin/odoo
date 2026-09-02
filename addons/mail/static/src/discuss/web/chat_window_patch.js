/** @odoo-module native */
import { ChatWindow } from "@mail/core/common/chat_window";
import { usePartnerAvatarCard } from "@mail/discuss/web/avatar_card/avatar_card_popover";
import { patch } from "@web/core/utils/patch";
patch(ChatWindow.prototype, {
    setup() {
        super.setup(...arguments);
        // the avatar sits in the header, which folds the window when clicked
        this.correspondentAvatarCard = usePartnerAvatarCard({ stopPropagation: true });
    },
    /** Only a one-to-one chat has a single correspondent to show a card for. */
    get correspondentPartner() {
        return this.thread?.channel_type === "chat"
            ? this.thread.correspondent?.partner_id
            : undefined;
    },
    /** @param {MouseEvent} ev */
    onClickCorrespondentAvatar(ev) {
        this.correspondentAvatarCard.open(ev, this.correspondentPartner);
    },
});
