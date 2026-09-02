/** @odoo-module native */
import { ChannelMemberList } from "@mail/discuss/core/common/channel_member_list";
import { AvatarCardPopover } from "@mail/discuss/web/avatar_card/avatar_card_popover";
import { patch } from "@web/core/utils/patch";
import { usePopover } from "@web/ui/popover";
patch(ChannelMemberList.prototype, {
    setup() {
        super.setup(...arguments);
        this.avatarCard = usePopover(AvatarCardPopover, {
            position: "right",
        });
    },
    /**
     * The card renders a bare partner, so a user account is not required:
     * external contacts (livechat visitors, email correspondents) get one too.
     *
     * @param {import("models").ChannelMember} member
     * @returns {boolean}
     */
    isClickable(member) {
        return Boolean(
            !this.store.inPublicPage && !member.guest_id && member.partner_id
        );
    },
    /**
     * @param {MouseEvent} ev
     * @param {import("models").ChannelMember} member
     */
    onClickAvatar(ev, member) {
        if (!this.isClickable(member)) {
            return;
        }
        if (!this.avatarCard.isOpen) {
            this.avatarCard.open(ev.currentTarget, {
                id: member.partner_id.id,
                model: "res.partner",
            });
        }
    },
});
Object.assign(ChannelMemberList.components, { AvatarCardPopover });
