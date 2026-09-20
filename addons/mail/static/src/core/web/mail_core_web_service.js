// @ts-check
/** @odoo-module native */
import { applyCounterAbsolute, applyCounterDelta } from "@mail/utils/common/counters";
import { reactive } from "@odoo/owl";
import { makeLogger } from "@web/core/debug/debug_logger";
import { registry } from "@web/core/registry";
const log = makeLogger("mail.bus");

export class MailCoreWeb {
    /**
     * @param {import("@web/env").OdooEnv} env
     * @param {import("services").ServiceFactories} services
     */
    constructor(env, services) {
        this.env = env;
        this.busService = services.bus_service;
        this.store = services["mail.store"];
    }

    _subscribeActivityUpdated() {
        this.busService.subscribe(
            "mail.activity/updated",
            /**
             * @param {Object} payload
             * @param {number} [payload.count_diff]
             * @param {boolean} [payload.activity_created]
             * @param {boolean} [payload.activity_deleted]
             * @param {{id: number}} metadata
             */
            (payload, { id: notifId }) => {
                log.pipeline("mail.activity/updated", () => payload);
                if (notifId <= this.store.activity_counter_bus_id) {
                    log.logic("mail.activity/updated stale", () => ({
                        notifId,
                        lastSeen: this.store.activity_counter_bus_id,
                    }));
                    return;
                }
                let countDiff = 0;
                if ("count_diff" in payload) {
                    countDiff = payload.count_diff;
                } else if (payload.activity_created) {
                    countDiff = 1;
                } else if (payload.activity_deleted) {
                    countDiff = -1;
                }
                this.store.activityCounter = Math.max(
                    this.store.activityCounter + countDiff,
                    0,
                );
                this.store.activity_counter_bus_id = notifId;
            },
        );
    }
    _subscribeMessageDeleted() {
        this.env.bus.addEventListener(
            "mail.message/delete",
            /** @param {CustomEvent<{message: import("models").Message, notifId: number}>} ev */
            ({ detail: { message, notifId } }) => {
                log.pipeline("mail.message/delete counters", () => ({
                    messageId: message.id,
                    needaction: message.needaction,
                    starred: message.starred,
                }));
                if (message.needaction) {
                    applyCounterDelta(this.store.inbox, "counter", -1, {
                        busId: notifId,
                    });
                }
                if (message.starred) {
                    applyCounterDelta(this.store.starred, "counter", -1, {
                        busId: notifId,
                    });
                }
                const thread = message.thread;
                if (message.needaction && thread) {
                    applyCounterDelta(thread, "message_needaction_counter", -1, {
                        busId: notifId,
                    });
                }
            },
        );
    }
    _subscribeInboxMessages() {
        this.busService.subscribe(
            "mail.message/inbox",
            /**
             * @param {{message_id: number, store_data: Object}} payload
             * @param {{id: number}} metadata
             */
            (payload, { id: notifId }) => {
                log.pipeline("mail.message/inbox", () => payload);
                const { message_id: messageId, store_data } = payload;
                this.store.insert(store_data);
                /** @type {import("models").Message} */
                const message = this.store["mail.message"].get(messageId);
                const inbox = this.store.inbox;
                applyCounterDelta(inbox, "counter", 1, { busId: notifId });
                if (!message) {
                    log.logic(
                        "mail.message/inbox message missing after insert",
                        () => ({
                            messageId,
                        }),
                    );
                    return;
                }
                inbox.messages.add(message);
                if (message.thread) {
                    applyCounterDelta(message.thread, "message_needaction_counter", 1, {
                        busId: notifId,
                    });
                }
                if (this.store.self_partner?.im_status?.includes("busy")) {
                    log.logic("mail.message/inbox notification suppressed: busy");
                    return;
                }
                this.store.env.services["mail.out_of_focus"].notify(message);
            },
        );
    }
    _subscribeMarkedAsRead() {
        this.busService.subscribe(
            "mail.message/mark_as_read",
            /**
             * @param {{message_ids: number[], needaction_inbox_counter: number}} payload
             * @param {{id: number}} metadata
             */
            (payload, { id: notifId }) => {
                log.pipeline("mail.message/mark_as_read", () => payload);
                const { message_ids: messageIds, needaction_inbox_counter } = payload;
                const inbox = this.store.inbox;
                for (const messageId of messageIds) {
                    const message = this.store["mail.message"].get(messageId);
                    if (!message) {
                        continue;
                    }
                    const thread = message.thread;
                    if (thread && message.needaction) {
                        applyCounterDelta(thread, "message_needaction_counter", -1, {
                            busId: notifId,
                        });
                    }
                    message.needaction = false;
                    inbox.messages.delete(message);
                    const history = this.store.history;
                    history.messages.add(message);
                }
                applyCounterAbsolute(
                    inbox,
                    "counter",
                    needaction_inbox_counter,
                    notifId,
                );
                if (inbox.counter > inbox.messages.length) {
                    log.logic("mark_as_read refills inbox", () => ({
                        counter: inbox.counter,
                        loaded: inbox.messages.length,
                    }));
                    inbox.fetchMoreMessages();
                }
            },
        );
    }
    setup() {
        this._subscribeActivityUpdated();
        this._subscribeMessageDeleted();
        this._subscribeInboxMessages();
        this._subscribeMarkedAsRead();
    }
}

export const mailCoreWeb = {
    dependencies: ["bus_service", "mail.store"],
    /**
     * @param {import("@web/env").OdooEnv} env
     * @param {import("services").ServiceFactories} services
     */
    start(env, services) {
        const mailCoreWeb = reactive(new MailCoreWeb(env, services));
        mailCoreWeb.setup();
        return mailCoreWeb;
    },
};

registry.category("services").add("mail.core.web", mailCoreWeb);
