/** @odoo-module native */
import { ActionPanel } from "@mail/core/common/action_panel";
import { ImStatus } from "@mail/core/common/im_status";
import { Component, onWillStart, onWillUpdateProps } from "@odoo/owl";
import { _t } from "@web/core/translation";
import { useService } from "@web/core/utils/hooks";
export class ChannelMemberList extends Component {
    static components = { ImStatus, ActionPanel };
    static props = ["thread", "openChannelInvitePanel", "className?"];
    static template = "discuss.ChannelMemberList";

    setup() {
        super.setup();
        this.store = useService("mail.store");
        onWillStart(() => {
            if (this.props.thread.fetchMembersState === "not_fetched") {
                this.props.thread.fetchChannelMembers();
            }
        });
        onWillUpdateProps(
            /** @param {{thread: import("models").Thread}} nextProps */ (nextProps) => {
                if (nextProps.thread.fetchMembersState === "not_fetched") {
                    nextProps.thread.fetchChannelMembers();
                }
            },
        );
    }

    get onlineSectionText() {
        return _t("Online - %(online_count)s", {
            online_count: this.props.thread.onlineMembers.length,
        });
    }

    get offlineSectionText() {
        return _t("Offline - %(offline_count)s", {
            offline_count: this.props.thread.offlineMembers.length,
        });
    }

    /**
     * Whether the member responds to a click at all. Here that means opening a
     * chat, so it needs a user; `discuss/core/web` widens it to any partner,
     * because there a click opens the avatar card instead.
     *
     * @param {import("models").ChannelMember} member
     * @returns {boolean}
     */
    isClickable(member) {
        return this.canOpenChatWith(member);
    }

    /**
     * Whether a chat can be opened with the member, which needs a user.
     *
     * @param {import("models").ChannelMember} member
     * @returns {boolean}
     */
    canOpenChatWith(member) {
        return Boolean(
            !this.store.inPublicPage &&
                !member.guest_id &&
                member.partner_id?.main_user_id
        );
    }

    /**
     * @param {MouseEvent} ev
     * @param {import("models").ChannelMember} member
     */
    onClickAvatar(ev, member) {
        if (!this.canOpenChatWith(member)) {
            return;
        }
        this.store.openChat({ partnerId: member.partner_id.id });
    }
}
