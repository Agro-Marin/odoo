// @ts-check
/** @odoo-module native */
import { reactive } from "@odoo/owl";
import { makeLogger } from "@web/core/debug/debug_logger";
import { registry } from "@web/core/registry";
const log = makeLogger("mail.bus");

export class MailCoreCommon {
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
            "ir.attachment/delete",
            /** @param {{id: number, message?: Object}} payload */ (payload) => {
                log.pipeline("ir.attachment/delete", () => payload);
                const { id: attachmentId, message: messageData } = payload;
                if (messageData) {
                    this.store["mail.message"].insert(messageData);
                }
                const attachment = this.store["ir.attachment"].get(attachmentId);
                attachment?.delete();
            },
        );
        this.busService.subscribe(
            "mail.message/delete",
            /**
             * @param {{message_ids: number[]}} payload
             * @param {{id: number}} metadata
             */
            (payload, { id: notifId }) => {
                log.pipeline("mail.message/delete", () => payload);
                for (const messageId of payload.message_ids) {
                    this.store.deletedMessageIds.add(messageId);
                    const message = this.store["mail.message"].get(messageId);
                    if (!message) {
                        continue;
                    }
                    this.env.bus.trigger("mail.message/delete", { message, notifId });
                    message.delete();
                }
            },
        );
        this.busService.subscribe(
            "mail.message/toggle_star",
            /**
             * @param {{message_ids: number[], starred: boolean}} payload
             * @param {Object} metadata
             */
            (payload, metadata) => {
                log.pipeline("mail.message/toggle_star", () => payload);
                this._handleNotificationToggleStar(payload, metadata);
            },
        );
        this.busService.subscribe(
            "res.users.settings",
            /** @param {Object|undefined} payload */ (payload) => {
                log.pipeline("res.users.settings", () => payload);
                if (payload) {
                    this.store.settings.update(payload);
                }
            },
        );
        this.busService.subscribe(
            "mail.record/insert",
            /** @param {Object} payload */ (payload) => {
                log.pipeline("mail.record/insert", () => payload);
                this.store.insert(payload);
            },
        );
    }

    /**
     * @param {{message_ids: number[], starred: boolean}} payload
     * @param {Object} metadata
     */
    _handleNotificationToggleStar(payload, metadata) {
        const { message_ids: messageIds, starred } = payload;
        log.logic("toggle_star", () => ({ messages: messageIds.length, starred }));
        this.store["mail.message"].insert(messageIds.map((id) => ({ id, starred })));
    }
}

export const mailCoreCommon = {
    dependencies: ["bus_service", "mail.store"],
    /**
     * @param {import("@web/env").OdooEnv} env
     * @param {import("services").ServiceFactories} services
     */
    start(env, services) {
        const mailCoreCommon = reactive(new MailCoreCommon(env, services));
        mailCoreCommon.setup();
        return mailCoreCommon;
    },
};

registry.category("services").add("mail.core.common", mailCoreCommon);
