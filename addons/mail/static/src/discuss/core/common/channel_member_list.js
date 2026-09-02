/** @odoo-module native */
import { ActionPanel } from "@mail/core/common/action_panel";
import { ImStatus } from "@mail/core/common/im_status";
import { makeSequential } from "@mail/utils/common/misc";
import { Component, onWillStart, onWillUpdateProps, useState } from "@odoo/owl";
import { _t } from "@web/core/translation";
import { useService } from "@web/core/utils/hooks";
export class ChannelMemberList extends Component {
    static components = { ImStatus, ActionPanel };
    static props = ["thread", "openChannelInvitePanel", "className?"];
    static template = "discuss.ChannelMemberList";

    setup() {
        super.setup();
        this.store = useService("mail.store");
        this.state = useState({ searchTerm: "" });
        // a slow answer to an old term must not overwrite a newer one
        this.sequential = makeSequential();
        onWillStart(() => {
            if (this.props.thread.fetchMembersState === "not_fetched") {
                this.props.thread.fetchChannelMembers();
            }
        });
        onWillUpdateProps(
            /** @param {{thread: import("models").Thread}} nextProps */ (nextProps) => {
                if (nextProps.thread.notEq(this.props.thread)) {
                    this.state.searchTerm = "";
                }
                if (nextProps.thread.fetchMembersState === "not_fetched") {
                    nextProps.thread.fetchChannelMembers();
                }
            },
        );
    }

    /**
     * @param {import("models").ChannelMember[]} members
     * @returns {import("models").ChannelMember[]}
     */
    filterBySearchTerm(members) {
        if (!this.state.searchTerm) {
            return members;
        }
        const term = this.state.searchTerm.toLowerCase();
        return members.filter((member) => member.name?.toLowerCase().includes(term));
    }

    /** @returns {import("models").ChannelMember[]} */
    get filteredOnlineMembers() {
        return this.filterBySearchTerm(this.props.thread.onlineMembers);
    }

    /** @returns {import("models").ChannelMember[]} */
    get filteredOfflineMembers() {
        return this.filterBySearchTerm(this.props.thread.offlineMembers);
    }

    /**
     * While searching, the "and N others" hint counts members this channel has
     * but never loaded, which says nothing about the term. Hide it.
     *
     * @returns {boolean}
     */
    get showUnknownMembersCount() {
        return !this.state.searchTerm;
    }

    /** @param {InputEvent} ev */
    onInputSearch(ev) {
        this.state.searchTerm = ev.target.value;
        const searchTerm = this.state.searchTerm;
        // the local list only holds what was already loaded; ask the server for
        // the members this channel has but this browser has never seen
        this.sequential(() => this.props.thread.fetchChannelMembers({ searchTerm }));
    }

    get onlineSectionText() {
        return _t("Online - %(online_count)s", {
            online_count: this.filteredOnlineMembers.length,
        });
    }

    get offlineSectionText() {
        return _t("Offline - %(offline_count)s", {
            offline_count: this.filteredOfflineMembers.length,
        });
    }

    /**
     * @param {import("models").ChannelMember} member
     * @returns {boolean}
     */
    canOpenChatWith(member) {
        return (
            !this.store.inPublicPage &&
            !member.guest_id &&
            member.partner_id.main_user_id
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
