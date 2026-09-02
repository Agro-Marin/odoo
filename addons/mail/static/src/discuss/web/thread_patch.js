/** @odoo-module native */
import { Thread } from "@mail/core/common/thread";
import { usePartnerAvatarCard } from "@mail/discuss/web/avatar_card/avatar_card_popover";
import { patch } from "@web/core/utils/patch";
patch(Thread.prototype, {
    setup() {
        super.setup(...arguments);
        this.correspondentAvatarCard = usePartnerAvatarCard();
    },
    /** Only a one-to-one chat has a single correspondent to show a card for. */
    get correspondentPartner() {
        const thread = this.props.thread;
        return thread?.channel_type === "chat"
            ? thread.correspondent?.partner_id
            : undefined;
    },
    /** @param {MouseEvent} ev */
    onClickCorrespondentAvatar(ev) {
        this.correspondentAvatarCard.open(ev, this.correspondentPartner);
    },
});
