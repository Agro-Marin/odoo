/** @odoo-module native */
import { discussComponentRegistry } from "@mail/core/common/discuss_component_registry";
import { FollowerSubtypeDialog } from "@mail/core/web/follower_subtype_dialog";
import { Component } from "@odoo/owl";
import { DropdownItem } from "@web/components/dropdown";
import { usePopover } from "@web/ui/popover";
/**
 * @typedef {Object} Props
 * @property {import("models").Follower} follower
 * @property {Function} [onFollowerChanged]
 * @property {Function} [close]
 * @extends {Component<Props, import("@web/env").OdooEnv>}
 */
export class Follower extends Component {
    static template = "mail.Follower";
    static props = ["follower", "onFollowerChanged?", "close?"];
    static components = { DropdownItem };

    setup() {
        // via the registry, not a direct import: `core/` does not depend on
        // `discuss/` — same shape as `message_patch.js` and `activity.js`
        this.avatarCard = usePopover(
            discussComponentRegistry.get("AvatarCardPopover"),
            { position: "right" },
        );
    }

    /** @param {MouseEvent} ev */
    onClickDetails(ev) {
        if (this.avatarCard.isOpen) {
            return;
        }
        // the card is anchored to the clicked item, so the follower list has
        // to stay open: no `props.close?.()` here
        this.avatarCard.open(ev.currentTarget, {
            id: this.props.follower.partner_id.id,
            model: "res.partner",
        });
    }

    async onClickEdit() {
        this.env.services.dialog.add(FollowerSubtypeDialog, {
            follower: this.props.follower,
            onFollowerChanged: () => this.props.onFollowerChanged?.(),
        });
        this.props.close?.();
    }

    async onClickRemove() {
        await this.props.follower.remove();
        this.props.onFollowerChanged?.();
    }
}
