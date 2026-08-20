/** @odoo-module native */
import { Component, onWillStart, useState } from "@odoo/owl";
import { rpc } from "@web/core/network";
import { _t } from "@web/core/translation";
import { useService } from "@web/core/utils/hooks";
import { Dialog } from "@web/ui/dialog";
/**
 * @typedef {Object} Props
 * @property {function} close
 * @property {import("models").Follower} follower
 * @property {function} onFollowerChanged
 * @extends {Component<Props, import("@web/env").OdooEnv>}
 */
export class FollowerSubtypeDialog extends Component {
    static components = { Dialog };
    static props = ["close", "follower", "onFollowerChanged"];
    static template = "mail.FollowerSubtypeDialog";

    setup() {
        super.setup();
        this.store = useService("mail.store");
        this.state = useState({
            /**
             * The subtypes this dialog offers, i.e. the ones the record exposes
             * through `_mail_get_message_subtypes`.
             * @type {import("models").MailMessageSubtype[]}
             */
            subtypes: [],
            /**
             * Draft selection, held here rather than on the follower record:
             * the record is shared state and must only change once the server
             * has accepted the new subscription.
             * @type {number[]}
             */
            selectedIds: [],
        });
        onWillStart(async () => {
            const { store_data, subtype_ids } = await rpc(
                "/mail/read_subscription_data",
                {
                    follower_id: this.props.follower.id,
                },
            );
            this.store.insert(store_data);
            this.state.subtypes = subtype_ids.map((id) =>
                this.store["mail.message.subtype"].get(id),
            );
            this.state.selectedIds = this.state.subtypes
                .filter((subtype) => subtype.in(this.props.follower.subtype_ids))
                .map((subtype) => subtype.id);
        });
    }

    /**
     * Subtypes the follower is subscribed to that this dialog never renders,
     * because `_mail_get_message_subtypes` filters them out: `hidden` ones, and
     * model-specific exclusions such as `project.task`'s rating subtype on a
     * step where rating is off. Applying rewrites the whole subscription, so
     * these have to ride along or pressing Apply silently revokes them.
     *
     * @returns {import("models").MailMessageSubtype[]}
     */
    get unmanagedSubtypes() {
        const managedIds = new Set(this.state.subtypes.map((subtype) => subtype.id));
        return [...this.props.follower.subtype_ids].filter(
            (subtype) => !managedIds.has(subtype.id),
        );
    }

    /**
     * @param {number} subtypeId
     * @returns {boolean}
     */
    isSelected(subtypeId) {
        return this.state.selectedIds.includes(subtypeId);
    }

    /**
     * @param {Event} ev
     * @param {import("models").MailMessageSubtype} subtype
     */
    onChangeCheckbox(ev, subtype) {
        if (ev.target.checked) {
            if (!this.isSelected(subtype.id)) {
                this.state.selectedIds.push(subtype.id);
            }
        } else {
            this.state.selectedIds = this.state.selectedIds.filter(
                (id) => id !== subtype.id,
            );
        }
    }

    async onClickApply() {
        // Unchecking everything the dialog offers means "stop following", as it
        // always has -- the unmanaged subtypes go with the subscription rather
        // than keeping it alive on their own.
        const selected = this.state.subtypes.filter((subtype) =>
            this.isSelected(subtype.id),
        );
        if (selected.length === 0) {
            await this.props.follower.remove();
        } else {
            const subtypes = [...selected, ...this.unmanagedSubtypes];
            await this.env.services.orm.call(
                this.props.follower.thread.model,
                "message_subscribe",
                [[this.props.follower.thread.id]],
                {
                    partner_ids: [this.props.follower.partner_id.id],
                    subtype_ids: subtypes.map((subtype) => subtype.id),
                },
            );
            this.props.follower.subtype_ids = subtypes;
            if (this.store.mt_comment.notIn(subtypes)) {
                this.props.follower.removeRecipient();
            }
            this.env.services.notification.add(
                _t("The subscription preferences were successfully applied."),
                { type: "success" },
            );
        }
        this.props.onFollowerChanged();
        this.props.close();
    }

    get title() {
        return _t("Edit Subscription of %(name)s", {
            name: this.props.follower.displayName,
        });
    }
}
