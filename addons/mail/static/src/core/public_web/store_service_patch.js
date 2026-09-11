// @ts-check
/** @odoo-module native */
import { fields } from "@mail/core/common/record";
import { Store, storeService } from "@mail/core/common/store_service";
import { router } from "@web/core/browser/router";
import { patch } from "@web/core/utils/patch";
/** @type {Partial<import("models").Store> & ThisType<import("models").Store>} */
const modelPatch = {
    setup() {
        super.setup();
        this.discuss = fields.One("DiscussApp");
        /** @type {number|undefined} */
        this.action_discuss_id;
    },
    onStarted() {
        super.onStarted(...arguments);
        this.discuss = this.DiscussApp.insert({ activeTab: "notification" });
        this.env.bus.addEventListener(
            "discuss.channel/new_message",
            /** @param {CustomEvent<{channel: import("models").Thread, message: import("models").Message, silent?: boolean}>} ev */
            ({ detail: { channel, message, silent } }) => {
                if (this.env.services.ui.isSmall || message.isSelfAuthored || silent) {
                    return;
                }
                channel.notifyMessageToUser(message);
            },
        );
    },
};
patch(Store.prototype, modelPatch);

patch(storeService, {
    /**
     * @param {import("@web/env").OdooEnv} env
     * @param {Object} services
     */
    start(env, services) {
        const store = super.start(...arguments);
        const discussActionIds = ["mail.action_discuss", "discuss"];
        if (store.action_discuss_id) {
            discussActionIds.push(store.action_discuss_id);
        }
        store.discuss.isActive ||= discussActionIds.includes(router.current.action);
        services.ui.bus.addEventListener("resize", () => {
            store.discuss.activeTab = "notification";
            if (services.ui.isSmall && store.discuss.thread?.channel_type) {
                store.discuss.activeTab = store.discuss.thread.channel_type;
            }
        });
        return store;
    },
});
