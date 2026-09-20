// @ts-check
/** @odoo-module native */
import { FollowerSubtypeDialog } from "@mail/core/web/follower_subtype_dialog";
import { Component } from "@odoo/owl";
import { DropdownItem } from "@web/components/dropdown";
import { makeLogger } from "@web/core/debug/debug_logger";
import { useService } from "@web/core/utils/hooks";

const log = makeLogger("mail.follower");
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
        this.store = useService("mail.store");
    }

    onClickDetails() {
        this.store.openDocument({
            id: this.props.follower.partner_id.id,
            model: "res.partner",
        });
        this.props.close?.();
    }

    async onClickEdit() {
        this.env.services.dialog.add(FollowerSubtypeDialog, {
            follower: this.props.follower,
            onFollowerChanged: () => this.props.onFollowerChanged?.(),
        });
        this.props.close?.();
    }

    async onClickRemove() {
        log.logic("onClickRemove", () => ({
            partnerId: this.props.follower.partner_id?.id,
        }));
        await this.props.follower.remove();
        this.props.onFollowerChanged?.();
    }
}
