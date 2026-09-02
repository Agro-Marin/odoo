/** @odoo-module native */
import { discussComponentRegistry } from "@mail/core/common/discuss_component_registry";
import { ImStatus } from "@mail/core/common/im_status";
import { useOpenChat } from "@mail/core/web/open_chat_hook";
import { Component } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { usePopover } from "@web/ui/popover";
export class AvatarCardPopover extends Component {
    static template = "mail.AvatarCardPopover";
    static components = { ImStatus };
    static props = {
        id: { type: Number, required: true },
        close: { type: Function, required: true },
        model: {
            type: String,
            /** @param {string} m */
            validate: (m) => ["res.users", "res.partner"].includes(m),
            optional: true,
        },
    };
    static defaultProps = {
        model: "res.users",
    };

    setup() {
        this.actionService = useService("action");
        this.store = useService("mail.store");
        this.openChat = useOpenChat(this.props.model);
        this.store.fetchStoreData("avatar_card", {
            id: this.props.id,
            model: this.props.model,
        });
    }

    get user() {
        if (this.props.model === "res.users") {
            return this.store["res.users"].get(this.props.id);
        }
        return undefined;
    }

    get partner() {
        if (this.props.model === "res.partner") {
            return this.store["res.partner"].get(this.props.id);
        }
        return this.user?.partner_id;
    }

    get name() {
        return this.partner?.name;
    }

    get email() {
        return this.partner?.email;
    }

    get phone() {
        return this.partner?.phone;
    }

    get showViewProfileBtn() {
        return this.partner;
    }

    get hasFooter() {
        return false;
    }

    async getProfileAction() {
        return {
            res_id: this.partner.id,
            res_model: "res.partner",
            type: "ir.actions.act_window",
            views: [[false, "form"]],
        };
    }

    onSendClick() {
        this.openChat(this.props.id);
        this.props.close();
    }

    /** @param {boolean} newWindow */
    async onClickViewProfile(newWindow) {
        const action = await this.getProfileAction();
        this.props.close();
        if (!action) {
            return;
        }
        this.actionService.doAction(action, { newWindow });
    }
}

/**
 * Opens the avatar card of a chat correspondent from the avatar the user clicked.
 * Wrapping `usePopover` here keeps the "which partner, and is one already open"
 * decision in one place: the avatars live in three different components.
 *
 * @param {Object} [param0]
 * @param {boolean} [param0.stopPropagation=false] set on avatars sitting inside
 *   a clickable header, so opening the card does not also trigger the header.
 */
export function usePartnerAvatarCard({ stopPropagation = false } = {}) {
    const avatarCard = usePopover(AvatarCardPopover);
    return {
        /**
         * @param {MouseEvent} ev
         * @param {import("models").ResPartner} [partner]
         */
        open(ev, partner) {
            if (!partner || avatarCard.isOpen) {
                return;
            }
            if (stopPropagation) {
                ev.stopPropagation();
            }
            avatarCard.open(ev.currentTarget, { id: partner.id, model: "res.partner" });
        },
    };
}

discussComponentRegistry.add("AvatarCardPopover", AvatarCardPopover);
