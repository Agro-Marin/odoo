/** @odoo-module native */
import { LinkNavigation } from "@mail/core/common/link_navigation_service";
import { AvatarCardPopover } from "@mail/discuss/web/avatar_card/avatar_card_popover";
import { patch } from "@web/core/utils/patch";

/**
 * Clicking an `@mention` pops the partner's avatar card. Backend only: the card
 * and the popover service it needs are both absent from the public page, which
 * is why the common layer declares this neutral.
 */
patch(LinkNavigation.prototype, {
    onClickPartnerMention(ev, id) {
        this.env.services.popover.add(ev.target, AvatarCardPopover, {
            id,
            model: "res.partner",
        });
    },
    /**
     * On a wide backend screen, following a link out of a channel leaves that
     * channel open behind it rather than swapping it away.
     */
    onLinkFollowed(fromThread) {
        super.onLinkFollowed(...arguments);
        if (!this.env.isSmall && fromThread?.model === "discuss.channel") {
            fromThread.open({ focus: false });
        }
    },
});
