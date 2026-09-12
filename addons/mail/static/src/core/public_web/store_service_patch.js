// @ts-check
/** @odoo-module native */
import { fields } from "@mail/core/common/record";
import { Store, storeService } from "@mail/core/common/store_service";
import { router } from "@web/core/browser/router";
import { makeLogger } from "@web/core/debug/debug_logger";
import { patch } from "@web/core/utils/patch";

const log = makeLogger("mail.discuss");
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
                    log.logic("new_message not notified", () => ({
                        channel: channel.localId,
                        messageId: message.id,
                        small: this.env.services.ui.isSmall,
                        selfAuthored: message.isSelfAuthored,
                        silent,
                    }));
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
        log.lifecycle("discuss app inserted", () => ({
            isActive: store.discuss.isActive,
            action: router.current.action,
        }));
        services.ui.bus.addEventListener("resize", () => {
            log.logic("resize resets active tab", () => ({
                small: services.ui.isSmall,
                thread: store.discuss.thread?.localId,
            }));
            store.discuss.activeTab = "notification";
            if (services.ui.isSmall && store.discuss.thread?.channel_type) {
                store.discuss.activeTab = store.discuss.thread.channel_type;
            }
        });
        return store;
    },
});
