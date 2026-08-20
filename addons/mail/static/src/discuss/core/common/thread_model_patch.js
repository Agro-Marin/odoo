/** @odoo-module native */
import { fields } from "@mail/core/common/record";
import { Thread } from "@mail/core/common/thread_model";
import { generateEmojisOnHtml } from "@mail/utils/common/format";
import {
    compareDatetime,
    effectWithCleanup,
    makeSequential,
    nearestGreaterThanOrEqual,
} from "@mail/utils/common/misc";
import { formatList } from "@web/core/l10n/utils";
import { rpc } from "@web/core/network";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { Deferred } from "@web/core/utils/concurrency";
import { createElementWithContent } from "@web/core/utils/dom/html";
import { patch } from "@web/core/utils/patch";
import { getOrigin, imageUrl } from "@web/core/utils/urls";
const commandRegistry = registry.category("discuss.channel_commands");

/** @type {Partial<typeof Thread> & ThisType<typeof Thread>} */
const threadStaticPatch = {
    new() {
        const thread = super.new(...arguments);
        effectWithCleanup({
            /**
             * @param {string|false} busChannel
             * @param {ReturnType<typeof import("@bus/services/bus_service").busService.start>} busService
             * @returns {(() => void)|undefined}
             */
            effect(busChannel, busService) {
                if (busService && busChannel) {
                    busService.addChannel(busChannel);
                    return () => busService.deleteChannel(busChannel);
                }
            },
            /** @param {import("models").Thread} thread */
            dependencies: (thread) => [
                thread.shouldSubscribeToBusChannel && thread.busChannel,
                thread.store.env.services.bus_service,
            ],
            reactiveTargets: [thread],
        });
        return thread;
    },
    /**
     * @param {{model: string, id: number}} data
     * @param {string[]} [fieldNames=[]]
     * @returns {Promise<import("models").Thread|undefined>}
     */
    async getOrFetch(data, fieldNames = []) {
        if (data.model !== "discuss.channel" || data.id < 1) {
            return super.getOrFetch(...arguments);
        }
        const thread = this.store.Thread.get({ id: data.id, model: data.model });
        if (thread?.fetchChannelInfoState === "fetched") {
            return Promise.resolve(thread);
        }
        if (thread?.channel_type && thread.self_member_id) {
            thread.fetchChannelInfoState = "fetched";
            return Promise.resolve(thread);
        }
        const fetchChannelInfoDeferred = this.store.channelIdsFetchingDeferred.get(
            data.id,
        );
        if (fetchChannelInfoDeferred) {
            return fetchChannelInfoDeferred;
        }
        const def = new Deferred();
        this.store.channelIdsFetchingDeferred.set(data.id, def);
        this.store.fetchChannel(data.id).then(
            () => {
                this.store.channelIdsFetchingDeferred.delete(data.id);
                const thread = this.store.Thread.get({
                    id: data.id,
                    model: data.model,
                });
                if (thread?.exists()) {
                    thread.fetchChannelInfoState = "fetched";
                    def.resolve(thread);
                } else {
                    def.resolve();
                }
            },
            () => {
                this.store.channelIdsFetchingDeferred.delete(data.id);
                const thread = this.store.Thread.get({
                    id: data.id,
                    model: data.model,
                });
                def.resolve(thread?.exists() ? thread : undefined);
            },
        );
        return def;
    },
};
patch(Thread, threadStaticPatch);

/**
 * @type {Partial<import("models").Thread> & ThisType<import("models").Thread>}
 */
const threadPatch = {
    setup() {
        super.setup();
        this.channel_member_ids = fields.Many("discuss.channel.member", {
            inverse: "channel_id",
            onDelete: (r) => r.delete(),
            sort: (m1, m2) => m1.id - m2.id,
        });
        this.correspondent = fields.One("discuss.channel.member", {
            /** @this {import("models").Thread} */
            compute() {
                return this.computeCorrespondent();
            },
        });
        this.correspondentCountry = fields.One("res.country", {
            /** @this {import("models").Thread} */
            compute() {
                return this.correspondent?.persona?.country_id ?? this.country_id;
            },
        });
        /** @type {"video_full_screen"|undefined} */
        this.default_display_mode = undefined;
        /** @type {"not_fetched"|"fetching"|"fetched"} */
        this.fetchChannelInfoState = "not_fetched";
        this.group_ids = fields.Many("res.groups");
        this.hasOtherMembersTyping = fields.Attr(false, {
            /** @this {import("models").Thread} */
            compute() {
                return this.otherTypingMembers.length > 0;
            },
        });
        this.hasSeenFeature = fields.Attr(false, {
            /** @this {import("models").Thread} */
            compute() {
                return this.store.channel_types_with_seen_infos.includes(
                    this.channel_type,
                );
            },
        });
        this.firstUnreadMessage = fields.One("mail.message", {
            /** @this {import("models").Thread} */
            compute() {
                if (!this.self_member_id) {
                    return null;
                }
                const messages = this.messages.filter((m) => !m.isNotification);
                const separator = this.self_member_id.new_message_separator_ui;
                if (separator === 0 && !this.loadOlder) {
                    return messages[0];
                }
                if (
                    !separator ||
                    messages.length === 0 ||
                    messages.at(-1).id < separator
                ) {
                    return null;
                }
                let message = this.store["mail.message"].get({ id: separator });
                if (!message || this.notEq(message.thread)) {
                    message = nearestGreaterThanOrEqual(
                        messages,
                        separator,
                        /** @param {import("models").Message} msg */ (msg) => msg.id,
                    );
                }
                return message;
            },
            inverse: "threadAsFirstUnread",
        });
        this.invited_member_ids = fields.Many("discuss.channel.member");
        this.last_interest_dt = fields.Datetime();
        this.lastInterestDt = fields.Datetime({
            /** @this {import("models").Thread} */
            compute() {
                const selfMemberLastInterestDt = this.self_member_id?.last_interest_dt;
                const lastInterestDt = this.last_interest_dt;
                return compareDatetime(selfMemberLastInterestDt, lastInterestDt) > 0
                    ? selfMemberLastInterestDt
                    : lastInterestDt;
            },
        });
        this.lastMessageSeenByAllId = fields.Attr(undefined, {
            /** @this {import("models").Thread} */
            compute() {
                if (!this.hasSeenFeature) {
                    return;
                }
                return this.channel_member_ids.reduce(
                    (lastMessageSeenByAllId, member) => {
                        if (
                            member.notEq(this.self_member_id) &&
                            member.seen_message_id
                        ) {
                            return lastMessageSeenByAllId
                                ? Math.min(
                                      lastMessageSeenByAllId,
                                      member.seen_message_id.id,
                                  )
                                : member.seen_message_id.id;
                        } else {
                            return lastMessageSeenByAllId;
                        }
                    },
                    undefined,
                );
            },
        });
        this.maxSeenMessageIdByOthers = fields.Attr(0, {
            /** @this {import("models").Thread} */
            compute() {
                if (!this.hasSeenFeature) {
                    return 0;
                }
                let max = 0;
                for (const member of this.channel_member_ids) {
                    if (
                        member.notEq(this.self_member_id) &&
                        member.persona &&
                        member.seen_message_id
                    ) {
                        max = Math.max(max, member.seen_message_id.id);
                    }
                }
                return max;
            },
        });
        this.maxFetchedMessageIdByOthers = fields.Attr(0, {
            /** @this {import("models").Thread} */
            compute() {
                if (!this.hasSeenFeature) {
                    return 0;
                }
                let max = 0;
                for (const member of this.channel_member_ids) {
                    if (
                        member.notEq(this.self_member_id) &&
                        member.persona &&
                        member.fetched_message_id
                    ) {
                        max = Math.max(max, member.fetched_message_id.id);
                    }
                }
                return max;
            },
        });
        this.lastSelfMessageSeenByEveryone = fields.One("mail.message", {
            /** @this {import("models").Thread} */
            compute() {
                if (!this.lastMessageSeenByAllId) {
                    return false;
                }
                let res;
                for (let i = this.persistentMessages.length - 1; i >= 0; i--) {
                    const message = this.persistentMessages[i];
                    if (
                        !message.isSelfAuthored ||
                        message.isNotification ||
                        message.id > this.lastMessageSeenByAllId
                    ) {
                        continue;
                    }
                    res = message;
                    break;
                }
                return res;
            },
        });
        this.markReadSequential = makeSequential();
        this.markedAsUnread = false;
        this.markingAsRead = false;
        /** @type {number|undefined} */
        this.member_count = undefined;
        /** @type {string} */
        this.name = undefined;
        this.channel_name_member_ids = fields.Many("discuss.channel.member");
        this.onlineMembers = fields.Many("discuss.channel.member", {
            /** @this {import("models").Thread} */
            compute() {
                return this.channel_member_ids
                    .filter((member) =>
                        this.store.onlineMemberStatuses.includes(member.im_status),
                    )
                    .sort((m1, m2) => this.store.sortMembers(m1, m2));
            },
        });
        this.offlineMembers = fields.Many("discuss.channel.member", {
            /** @this {import("models").Thread} */
            compute() {
                return this._computeOfflineMembers().sort((m1, m2) =>
                    this.store.sortMembers(m1, m2),
                );
            },
        });
        this.otherTypingMembers = fields.Many("discuss.channel.member", {
            /** @this {import("models").Thread} */
            compute() {
                return this.typingMembers.filter(
                    (member) => !member.persona?.eq(this.store.self),
                );
            },
        });
        this.self_member_id = fields.One("discuss.channel.member", {
            inverse: "threadAsSelf",
        });
        this.scrollUnread = true;
        this.toggleBusSubscription = fields.Attr(false, {
            /** @this {import("models").Thread} */
            compute() {
                return (
                    this.model === "discuss.channel" &&
                    this.self_member_id?.memberSince >=
                        this.store.env.services.bus_service.startedAt
                );
            },
            /** @this {import("models").Thread} */
            onUpdate() {
                this.store.updateBusSubscription();
            },
        });
        this.typingMembers = fields.Many("discuss.channel.member", {
            inverse: "threadAsTyping",
        });
    },
    /** @returns {import("models").ChannelMember[]} */
    _computeOfflineMembers() {
        return this.channel_member_ids.filter(
            (member) => !this.store.onlineMemberStatuses.includes(member.im_status),
        );
    },
    get isChannelKind() {
        return this.model === "discuss.channel";
    },
    get isDirectChat() {
        return this.channel_type === "chat";
    },
    get isChatChannel() {
        return ["chat", "group"].includes(this.channel_type);
    },
    get allowedToLeaveChannelTypes() {
        return ["channel", "group"];
    },
    get canLeave() {
        return (
            this.allowedToLeaveChannelTypes.includes(this.channel_type) &&
            this.group_ids.length === 0 &&
            this.store.self_partner
        );
    },
    get allowedToUnpinChannelTypes() {
        return ["chat"];
    },
    get canUnpin() {
        return (
            this.allowedToUnpinChannelTypes.includes(this.channel_type) ||
            super.canUnpin
        );
    },
    computeDisplayToSelf() {
        return (
            this.self_member_id?.is_pinned ||
            (["channel", "group"].includes(this.channel_type) &&
                this.hasSelfAsMember &&
                !this.parent_channel_id)
        );
    },
    get typesAllowingCalls() {
        return ["chat", "channel", "group"];
    },
    get allowCalls() {
        return (
            !this.isTransient &&
            this.typesAllowingCalls.includes(this.channel_type) &&
            !this.correspondent?.persona.eq(this.store.odoobot)
        );
    },
    get supportsCustomChannelName() {
        return this.isChatChannel && this.channel_type !== "group";
    },
    get allowDescription() {
        return ["channel", "group"].includes(this.channel_type);
    },
    get invitationLink() {
        if (!this.uuid || this.channel_type === "chat") {
            return undefined;
        }
        return `${getOrigin()}/chat/${this.id}/${this.uuid}`;
    },
    get hasAttachmentPanel() {
        return this.isChannelKind;
    },
    get canFetchMessages() {
        return this.isChannelKind || super.canFetchMessages;
    },
    get busKeepsMessagesFresh() {
        return this.isChannelKind || super.busKeepsMessagesFresh;
    },
    getFetchParams() {
        if (this.isChannelKind) {
            return { channel_id: this.id };
        }
        return super.getFetchParams();
    },
    getFetchRoute() {
        if (this.isChannelKind) {
            return "/discuss/channel/messages";
        }
        return super.getFetchRoute();
    },
    get imStatusMember() {
        return this.channel_type === "chat" ? this.correspondent : undefined;
    },
    /**
     * @param {import("models").Persona} persona
     * @returns {boolean}
     */
    isChatWith(persona) {
        return (
            this.channel_type === "chat" &&
            Boolean(this.correspondent?.persona.eq(persona))
        );
    },
    get chatWindowComposerType() {
        return this.isChannelKind ? undefined : super.chatWindowComposerType;
    },
    get composerPlaceholder() {
        if (this.channel_type === "channel") {
            return _t("Message #%(threadName)s…", { threadName: this.displayName });
        }
        return super.composerPlaceholder;
    },
    /**
     * @param {import("models").Message} message
     * @returns {string}
     */
    outOfFocusNotificationTitle(message) {
        if (this.channel_type === "channel") {
            return _t("%(author name)s from %(channel name)s", {
                "author name": message.authorName,
                "channel name": this.displayName,
            });
        }
        return super.outOfFocusNotificationTitle(...arguments);
    },
    get hasStartOfConversationBanner() {
        return ["channel", "group", "chat"].includes(this.channel_type);
    },
    get conversationStartTitle() {
        if (this.channel_type === "channel") {
            return _t("Welcome to #%(channelName)s!", { channelName: this.name });
        }
        return super.conversationStartTitle;
    },
    get conversationStartSubtitle() {
        if (this.channel_type === "channel") {
            return _t("This is the start of the #%(channelName)s channel", {
                channelName: this.name,
            });
        }
        if (this.channel_type === "group") {
            return _t("This is the start of %(conversationName)s group", {
                conversationName: this.displayName,
            });
        }
        return _t("This is the start of your direct chat with %(userName)s", {
            userName: this.displayName,
        });
    },
    get newMessageSeparatorId() {
        return this.self_member_id?.new_message_separator_ui;
    },
    _getActualModelName() {
        return this.isChannelKind ? "discuss.channel" : super._getActualModelName();
    },
    /**
     * @param {import("@mail/discuss/core/common/channel_commands").ChannelCommand} command
     * @param {string} [body=""]
     * @returns {Promise<any>}
     */
    executeCommand(command, body = "") {
        return this.store.env.services.orm.call(
            "discuss.channel",
            command.methodName,
            [[this.id]],
            { body },
        );
    },
    async markAsFetched() {
        await this.store.env.services.orm.silent.call(
            "discuss.channel",
            "channel_fetched",
            [[this.id]],
        );
    },
    /** @param {string} data */
    async notifyAvatarToServer(data) {
        await rpc("/discuss/channel/update_avatar", {
            channel_id: this.id,
            data,
        });
    },
    /**
     * @param {string} description
     * @throws {Error}
     */
    async notifyDescriptionToServer(description) {
        const previousDescription = this.description;
        this.description = description;
        try {
            return await this.store.env.services.orm.call(
                "discuss.channel",
                "channel_change_description",
                [[this.id]],
                { description },
            );
        } catch (e) {
            this.description = previousDescription;
            throw e;
        }
    },
    /** @param {string} name */
    async rename(name) {
        const newName = name.trim();
        if (
            newName !== this.displayName &&
            ((newName && this.channel_type === "channel") || this.isChatChannel)
        ) {
            if (this.channel_type === "channel" || this.channel_type === "group") {
                const previousName = this.name;
                this.name = newName;
                try {
                    await this.store.env.services.orm.call(
                        "discuss.channel",
                        "channel_rename",
                        [[this.id]],
                        { name: newName },
                    );
                } catch (e) {
                    this.name = previousName;
                    throw e;
                }
            } else if (this.supportsCustomChannelName) {
                const member = this.self_member_id;
                const previousCustomName = member?.custom_channel_name;
                if (member) {
                    member.custom_channel_name = newName;
                }
                try {
                    await this.store.env.services.orm.call(
                        "discuss.channel",
                        "channel_set_custom_name",
                        [[this.id]],
                        { name: newName },
                    );
                } catch (e) {
                    if (member) {
                        member.custom_channel_name = previousCustomName;
                    }
                    throw e;
                }
            }
        }
        return super.rename(...arguments);
    },
    /**
     * @param {Object} [options]
     * @param {boolean} [options.force=false]
     */
    async leaveChannel({ force = false } = {}) {
        if (
            this.channel_type !== "group" &&
            this.create_uid?.eq(this.store.self_partner?.main_user_id) &&
            !force
        ) {
            await this.askLeaveConfirmation(
                _t(
                    "You are the administrator of this channel. Are you sure you want to leave?",
                ),
            );
        }
        if (this.channel_type === "group" && !force) {
            await this.askLeaveConfirmation(
                _t(
                    "You are about to leave this group conversation and will no longer have access to it unless you are invited again. Are you sure you want to continue?",
                ),
            );
        }
        await this.closeChatWindow();
        await this.store.env.services.orm.silent.call(
            "discuss.channel",
            "action_unfollow",
            [this.id],
        );
    },
    get allow_invite_by_email() {
        return (
            this.channel_type === "group" ||
            (this.channel_type === "channel" && !this.group_public_id)
        );
    },
    get areAllMembersLoaded() {
        return this.member_count === this.channel_member_ids.length;
    },
    get avatarUrl() {
        if (this.channel_type === "channel" || this.channel_type === "group") {
            return imageUrl("discuss.channel", this.id, "avatar_128", {
                unique: this.avatar_cache_key,
            });
        }
        if (this.channel_type === "chat" && this.correspondent) {
            return this.correspondent.avatarUrl;
        }
        return super.avatarUrl;
    },
    async checkReadAccess() {
        const res = await super.checkReadAccess();
        if (!res && this.model === "discuss.channel") {
            return this.channel_type;
        }
        return res;
    },
    /** @returns {import("models").ChannelMember} */
    computeCorrespondent() {
        if (["channel", "group"].includes(this.channel_type)) {
            return undefined;
        }
        const correspondents = this.correspondents;
        if (correspondents.length === 1) {
            return correspondents[0];
        }
        if (correspondents.length === 0 && this.channel_member_ids.length === 1) {
            return this.channel_member_ids[0];
        }
        return undefined;
    },
    /** @returns {import("models").ChannelMember[]} */
    get correspondents() {
        return this.channel_member_ids.filter(({ persona }) =>
            persona?.notEq(this.store.self),
        );
    },
    get displayName() {
        if (
            this.supportsCustomChannelName &&
            this.self_member_id?.custom_channel_name
        ) {
            return this.self_member_id.custom_channel_name;
        }
        if (this.channel_type === "chat" && this.correspondent) {
            return this.correspondent.name;
        }
        if (this.channel_name_member_ids.length && !this.name) {
            const nameParts = [...this.channel_name_member_ids]
                .sort((m1, m2) => m1.id - m2.id)
                .slice(0, 3)
                .map((member) => member.name);
            if (this.member_count > 3) {
                const remaining = this.member_count - 3;
                nameParts.push(
                    remaining === 1 ? _t("1 other") : _t("%s others", remaining),
                );
            }
            return formatList(nameParts);
        }
        if (this.model === "discuss.channel" && this.name) {
            return this.name;
        }
        return super.displayName;
    },
    async fetchChannelMembers() {
        if (this.fetchMembersState === "pending") {
            return;
        }
        const previousState = this.fetchMembersState;
        this.fetchMembersState = "pending";
        const known_member_ids = this.channel_member_ids.map(
            (channelMember) => channelMember.id,
        );
        let data;
        try {
            data = await rpc("/discuss/channel/members", {
                channel_id: this.id,
                known_member_ids: known_member_ids,
            });
        } catch (e) {
            this.fetchMembersState = previousState;
            throw e;
        }
        this.fetchMembersState = "fetched";
        this.store.insert(data);
    },
    /** @param {number} [limit=30] */
    async fetchMoreAttachments(limit = 30) {
        if (this.isLoadingAttachments || this.areAttachmentsLoaded) {
            return;
        }
        this.isLoadingAttachments = true;
        try {
            const data = await rpc("/discuss/channel/attachments", {
                before: Math.min(...this.attachments.map(({ id }) => id)),
                channel_id: this.id,
                limit,
            });
            this.store.insert(data.store_data);
            if (!data.has_more) {
                this.areAttachmentsLoaded = true;
            }
        } finally {
            this.isLoadingAttachments = false;
        }
    },
    get hasMemberList() {
        return ["channel", "group"].includes(this.channel_type);
    },
    get hasSelfAsMember() {
        return Boolean(this.self_member_id);
    },
    get importantCounter() {
        if (this.isChatChannel && this.self_member_id?.message_unread_counter_ui) {
            return this.self_member_id.message_unread_counter_ui;
        }
        if (this.discussAppCategory?.id === "channels") {
            if (this.store.settings.channel_notifications === "no_notif") {
                return 0;
            }
            if (
                this.store.settings.channel_notifications === "all" &&
                !this.self_member_id?.mute_until_dt
            ) {
                return this.self_member_id?.message_unread_counter_ui;
            }
        }
        return super.importantCounter;
    },
    isDisplayedOnUpdate() {
        super.isDisplayedOnUpdate(...arguments);
        if (!this.self_member_id) {
            return;
        }
        if (!this.isDisplayed) {
            this.self_member_id.new_message_separator_ui =
                this.self_member_id.new_message_separator;
            this.markedAsUnread = false;
        }
    },
    get isUnread() {
        return this.self_member_id?.message_unread_counter > 0 || super.isUnread;
    },
    markAsRead() {
        super.markAsRead(...arguments);
        if (!this.self_member_id) {
            return;
        }
        const newestPersistentMessage = this.newestPersistentOfAllMessage;
        if (!newestPersistentMessage) {
            return;
        }
        const alreadyReadBySelf =
            this.self_member_id.seen_message_id?.id >= newestPersistentMessage.id &&
            this.self_member_id.new_message_separator > newestPersistentMessage.id;
        if (alreadyReadBySelf) {
            return;
        }
        this.markReadSequential(async () => {
            this.markingAsRead = true;
            try {
                return await rpc(
                    "/discuss/channel/mark_as_read",
                    {
                        channel_id: this.id,
                        last_message_id: newestPersistentMessage.id,
                    },
                    { silent: true },
                ).catch((e) => {
                    if (e.code !== 404) {
                        throw e;
                    }
                });
            } finally {
                this.markingAsRead = false;
            }
        });
    },
    /** @returns {import("models").ChannelMember[]} */
    get membersThatCanSeen() {
        return this.channel_member_ids;
    },
    get needactionCounter() {
        return this.isChatChannel
            ? (this.self_member_id?.message_unread_counter ?? 0)
            : super.needactionCounter;
    },
    /** @param {import("models").Message} message */
    onNewSelfMessage(message) {
        if (
            !this.self_member_id ||
            message.id < this.self_member_id.seen_message_id?.id
        ) {
            return;
        }
        this.self_member_id.seen_message_id = message;
        this.self_member_id.new_message_separator = message.id + 1;
        this.self_member_id.new_message_separator_ui =
            this.self_member_id.new_message_separator;
        this.markedAsUnread = false;
    },
    /**
     * @param {Object} [options]
     * @returns {boolean}
     */
    openChatUI(options) {
        if (!this.isChannelKind) {
            return super.openChatUI(...arguments);
        }
        if (this.openChannel()) {
            return true;
        }
        this.openChatWindow(options);
        return true;
    },
    get hasOptimisticPost() {
        return this.isChannelKind;
    },
    /**
     * @param {number} tmpId
     * @param {ReturnType<import("@odoo/owl").markup>} body
     * @param {Object} postData
     * @returns {Promise<import("models").Message|undefined>}
     */
    async makeOptimisticPendingMessage(tmpId, body, postData) {
        if (!this.hasOptimisticPost) {
            return super.makeOptimisticPendingMessage(...arguments);
        }
        const { attachments, parentId } = postData;
        const tmpData = {
            id: tmpId,
            attachment_ids: attachments,
            res_id: this.id,
            model: "discuss.channel",
        };
        if (this.store.self_partner) {
            tmpData.author_id = this.store.self_partner;
        } else {
            tmpData.author_guest_id = this.store.self_guest;
        }
        if (parentId) {
            tmpData.parent_id = this.store["mail.message"].get(parentId);
        }
        return this.store["mail.message"].insert({
            ...tmpData,
            body: await generateEmojisOnHtml(body),
            isPending: true,
            thread: this,
        });
    },
    /** @param {string} body */
    async post(body) {
        const textContent = createElementWithContent("div", body).textContent.trim();
        if (this.model === "discuss.channel" && textContent.startsWith("/")) {
            const [firstWord] = textContent.substring(1).split(/\s/);
            const command = commandRegistry.get(firstWord, false);
            if (
                command &&
                (!command.condition ||
                    command.condition({ store: this.store, thread: this })) &&
                (!command.channel_types ||
                    command.channel_types.includes(this.channel_type))
            ) {
                await this.executeCommand(command, textContent);
                return;
            }
        }
        return super.post(...arguments);
    },
    get shouldSubscribeToBusChannel() {
        return Boolean(
            this.model === "discuss.channel" &&
            !this.isTransient &&
            !this.self_member_id &&
            (this.isLocallyPinned || this.chat_window?.isOpen),
        );
    },
    get showUnreadBanner() {
        return this.self_member_id?.message_unread_counter_ui > 0;
    },
    get unknownMembersCount() {
        return (this.member_count ?? 0) - this.channel_member_ids.length;
    },
};
patch(Thread.prototype, threadPatch);
