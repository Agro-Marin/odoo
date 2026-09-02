/** @odoo-module native */
import { DiscussContent } from "@mail/core/public_web/discuss_content";
import { usePartnerAvatarCard } from "@mail/discuss/web/avatar_card/avatar_card_popover";
import { patch } from "@web/core/utils/patch";
patch(DiscussContent.prototype, {
    setup() {
        super.setup(...arguments);
        this.correspondentAvatarCard = usePartnerAvatarCard();
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
