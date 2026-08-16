/** @odoo-module native */
import { reactive } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
export class DiscussCoreWeb {
    /**
     * @param {import("@web/env").OdooEnv} env
     * @param {import("services").ServiceFactories} services
     */
    constructor(env, services) {
        this.env = env;
        this.busService = services.bus_service;
        this.notificationService = services.notification;
        this.ui = services.ui;
        this.store = services["mail.store"];
        this.multiTab = services.multi_tab;
    }

    setup() {
        this.busService.subscribe(
            "res.users/connection",
            /** @param {{partnerId: number, username: string}} payload */
            async ({ partnerId, username }) => {
                const notification = _t(
                    "%(user)s just connected for the first time. Wish them luck!",
                    {
                        user: username,
                    },
                );
                this.notificationService.add(notification, { type: "info" });
                if (!(await this.multiTab.isOnMainTab())) {
                    return;
                }
                const chat = await this.store.getChat({ partnerId });
                if (chat && !this.ui.isSmall) {
                    chat.openChatWindow({ focus: false });
                }
            },
        );
        this.env.bus.addEventListener(
            "mail.message/delete",
            /** @param {CustomEvent<{message: import("models").Message}>} ev */
            ({ detail: { message } }) => {
                if (
                    message.thread?.model === "discuss.channel" &&
                    this.store.channels.status !== "fetched"
                ) {
                    this.store.channels.invalidate();
                    this.store.channels.fetch();
                }
            },
        );
    }
}

export const discussCoreWeb = {
    dependencies: ["bus_service", "mail.store", "notification", "ui", "multi_tab"],
    /**
     * @param {import("@web/env").OdooEnv} env
     * @param {import("services").ServiceFactories} services
     */
    start(env, services) {
        const discussCoreWeb = reactive(new DiscussCoreWeb(env, services));
        discussCoreWeb.setup();
        return discussCoreWeb;
    },
};

registry.category("services").add("discuss.core.web", discussCoreWeb);
