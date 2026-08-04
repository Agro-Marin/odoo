/** @odoo-module native */
import { applyCounterAbsolute, applyCounterDelta } from "@mail/utils/common/counters";
import { reactive } from "@odoo/owl";
import { registry } from "@web/core/registry";
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

    setup() {
        this.busService.subscribe(
            "mail.activity/updated",
            (payload, { id: notifId }) => {
                if (notifId <= this.store.activity_counter_bus_id) {
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
                // advance the bus id so a redelivered notification (bus
                // reconnection catch-up) is not applied a second time.
                this.store.activity_counter_bus_id = notifId;
            },
        );
        this.env.bus.addEventListener(
            "mail.message/delete",
            ({ detail: { message, notifId } }) => {
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
        this.busService.subscribe("mail.message/inbox", (payload, { id: notifId }) => {
            const { message_id: messageId, store_data } = payload;
            this.store.insert(store_data);
            /** @type {import("models").Message} */
            const message = this.store["mail.message"].get(messageId);
            const inbox = this.store.inbox;
            applyCounterDelta(inbox, "counter", 1, { busId: notifId });
            inbox.messages.add(message);
            if (message.thread) {
                applyCounterDelta(message.thread, "message_needaction_counter", 1, {
                    busId: notifId,
                });
            }
            if (this.store.self_partner?.im_status?.includes("busy")) {
                return;
            }
            this.store.env.services["mail.out_of_focus"].notify(message);
        });
        this.busService.subscribe(
            "mail.message/mark_as_read",
            (payload, { id: notifId }) => {
                const { message_ids: messageIds, needaction_inbox_counter } = payload;
                const inbox = this.store.inbox;
                for (const messageId of messageIds) {
                    // ignore not yet known messages: linking them straight to
                    // the cache would show them partially
                    const message = this.store["mail.message"].get(messageId);
                    if (!message) {
                        continue;
                    }
                    // update the thread counter before removing the message from
                    // Inbox, so the `needaction` check below still holds
                    const thread = message.thread;
                    if (thread && message.needaction) {
                        applyCounterDelta(thread, "message_needaction_counter", -1, {
                            busId: notifId,
                        });
                    }
                    message.needaction = false;
                    inbox.messages.delete({ id: messageId });
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
                    inbox.fetchMoreMessages();
                }
            },
        );
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
