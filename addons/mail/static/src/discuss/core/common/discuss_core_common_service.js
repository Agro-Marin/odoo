/** @odoo-module native */
import { applyCounterDelta } from "@mail/utils/common/counters";
import { markup, reactive } from "@odoo/owl";
import { registry } from "@web/core/registry";
export class DiscussCoreCommon {
    /**
     * @param {import("@web/env").OdooEnv} env
     * @param {import("services").ServiceFactories} services
     */
    constructor(env, services) {
        this.busService = services.bus_service;
        this.env = env;
        this.store = services["mail.store"];
    }

    setup() {
        this.busService.subscribe(
            "discuss.channel/delete",
            /**
             * @param {{id: number}} payload
             * @param {{id: number}} metadata
             */
            (payload, metadata) => {
                const thread = this.store.Thread.insert({
                    id: payload.id,
                    model: "discuss.channel",
                });
                this._handleNotificationChannelDelete(thread, metadata);
            },
        );
        this.busService.subscribe(
            "discuss.channel/new_message",
            /**
             * @param {{data: Object, id: number, message_id?: number, silent?: boolean, temporary_id?: number}} payload
             * @param {{id: number}} metadata
             */
            (payload, metadata) => {
                this.store.insert(payload.data);
                this._handleNotificationNewMessage(payload, metadata);
            },
        );
        this.busService.subscribe(
            "discuss.channel/transient_message",
            /** @param {{body: string, channel_id: number}} payload */ (payload) => {
                const { body, channel_id } = payload;
                const message = this.store["mail.message"].insert({
                    author_id: this.store.odoobot,
                    body: markup(body),
                    id: this.store.getNextTemporaryId(),
                    subtype_id: this.store.mt_note,
                    is_transient: true,
                    thread: { id: channel_id, model: "discuss.channel" },
                });
                message.thread.messages.push(message);
                message.thread.transientMessages.push(message);
            },
        );
        this.busService.subscribe(
            "discuss.channel.member/fetched",
            /**
             * @param {Object} payload
             * @param {number} payload.channel_id
             * @param {number} payload.id
             * @param {number} payload.last_message_id
             * @param {number} payload.partner_id
             */
            (payload) => {
                const { channel_id, id, last_message_id, partner_id } = payload;
                this.store["discuss.channel.member"].insert({
                    id,
                    fetched_message_id: { id: last_message_id },
                    partner_id: { id: partner_id },
                    thread: { id: channel_id, model: "discuss.channel" },
                });
            },
        );
        this.env.bus.addEventListener(
            "mail.message/delete",
            /** @param {CustomEvent<{message: import("models").Message, notifId: number}>} ev */
            ({ detail: { message, notifId } }) => {
                if (message.thread) {
                    const { self_member_id } = message.thread;
                    if (
                        self_member_id &&
                        !message.isNotification &&
                        message.id > (self_member_id.seen_message_id?.id ?? 0)
                    ) {
                        applyCounterDelta(
                            self_member_id,
                            "message_unread_counter",
                            -1,
                            { busId: notifId },
                        );
                    }
                }
            },
        );
    }

    /**
     * @param {import("models").Thread} thread
     * @param {{ notifId: number}} metadata
     */
    async _handleNotificationChannelDelete(thread, metadata) {
        await thread.closeChatWindow({ force: true });
        thread.messages.splice(0, thread.messages.length);
        thread.delete();
    }

    /**
     * @param {Object} payload
     * @param {Object} payload.data
     * @param {number} payload.id
     * @param {number} [payload.message_id]
     * @param {boolean} [payload.silent]
     * @param {number} [payload.temporary_id]
     * @param {{id: number}} metadata
     */
    async _handleNotificationNewMessage(payload, { id: notifId }) {
        const { data, id: channelId, message_id, silent, temporary_id } = payload;
        const channel = await this.store.Thread.getOrFetch({
            model: "discuss.channel",
            id: channelId,
        });
        if (!channel?.exists()) {
            return;
        }
        const message = this.store["mail.message"].get(
            message_id ?? data["mail.message"]?.[0],
        );
        if (!message) {
            return;
        }
        if (message.notIn(channel.messages)) {
            if (!channel.loadNewer) {
                channel.addOrReplaceMessage(
                    message,
                    this.store["mail.message"].get(temporary_id),
                );
            } else if (
                channel.status === "loading" &&
                message.notIn(channel.pendingNewMessages)
            ) {
                channel.pendingNewMessages.push(message);
            }
            if (message.isSelfAuthored) {
                channel.onNewSelfMessage(message);
            } else {
                if (
                    channel.isDisplayed &&
                    channel.self_member_id?.new_message_separator_ui === 0
                ) {
                    channel.self_member_id.new_message_separator_ui = message.id;
                }
                if (!channel.isDisplayed && channel.self_member_id) {
                    channel.scrollUnread = true;
                }
                if (channel.self_member_id && !message.isNotification) {
                    applyCounterDelta(
                        channel.self_member_id,
                        "message_unread_counter",
                        1,
                        { busId: notifId },
                    );
                }
            }
        }
        if (
            channel.channel_type !== "channel" &&
            this.store.self_partner &&
            channel.self_member_id
        ) {
            channel.markAsFetched();
        }
        if (
            !channel.loadNewer &&
            !message.isSelfAuthored &&
            channel.composer.isFocused &&
            this.store.self_partner &&
            channel.newestPersistentMessage?.eq(channel.newestMessage) &&
            !channel.markedAsUnread
        ) {
            channel.markAsRead();
        }
        this.env.bus.trigger("discuss.channel/new_message", {
            channel,
            message,
            silent,
        });
        const authorMember = channel.channel_member_ids.find((member) =>
            member.persona?.eq(message.author),
        );
        if (authorMember) {
            authorMember.seen_message_id = message;
        }
    }
}

export const discussCoreCommon = {
    dependencies: ["bus_service", "mail.out_of_focus", "mail.store"],
    /**
     * @param {import("@web/env").OdooEnv} env
     * @param {import("services").ServiceFactories} services
     */
    start(env, services) {
        const discussCoreCommon = reactive(new DiscussCoreCommon(env, services));
        discussCoreCommon.setup(env, services);
        return discussCoreCommon;
    },
};

registry.category("services").add("discuss.core.common", discussCoreCommon);
