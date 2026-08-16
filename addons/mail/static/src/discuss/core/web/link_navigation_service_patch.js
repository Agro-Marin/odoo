/** @odoo-module native */
import { LinkNavigation } from "@mail/core/common/link_navigation_service";
import { AvatarCardPopover } from "@mail/discuss/web/avatar_card/avatar_card_popover";
import { patch } from "@web/core/utils/patch";

patch(LinkNavigation.prototype, {
    /**
     * @param {MouseEvent} ev
     * @param {number} id
     */
    onClickPartnerMention(ev, id) {
        this.env.services.popover.add(ev.target, AvatarCardPopover, {
            id,
            model: "res.partner",
        });
    },
    /** @param {import("models").Thread} [fromThread] */
    onLinkFollowed(fromThread) {
        super.onLinkFollowed(...arguments);
        if (!this.env.isSmall && fromThread?.model === "discuss.channel") {
            fromThread.open({ focus: false });
        }
    },
});
