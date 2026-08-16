/** @odoo-module native */
import { fields } from "@mail/core/common/record";
import { Store } from "@mail/core/common/store_service";
import { snapshotCounter } from "@mail/utils/common/counters";
import { browser } from "@web/core/browser/browser";
import { _t } from "@web/core/translation";
import { patch } from "@web/core/utils/patch";
const unread_store = (() => {
    if (!window.idbKeyval) {
        return undefined;
    }
    return new window.idbKeyval.Store("odoo-mail-unread-db", "odoo-mail-unread-store");
})();

/**
 * @type {Partial<import("models").Store> & ThisType<import("models").Store>}
 */
const StorePatch = {
    setup() {
        super.setup(...arguments);
        this.activityCounter = 0;
        this.activity_counter_bus_id = 0;
        /** @type {Object[]} */
        this.activityGroups = fields.Attr([], {
            /** @this {import("models").Store} */
            onUpdate() {
                this.onUpdateActivityGroups();
            },
            /** @this {import("models").Store} */
            sort(g1, g2) {
                /** @param {{id: number, model: string}} activityGroup */
                const getSortId = (activityGroup) =>
                    activityGroup.model === "mail.activity"
                        ? Number.MAX_VALUE
                        : activityGroup.id;
                return getSortId(g1) - getSortId(g2);
            },
        });
        this.globalCounter = fields.Attr(0, {
            /** @this {import("models").Store} */
            compute() {
                return this.computeGlobalCounter();
            },
            /** @this {import("models").Store} */
            onUpdate() {
                this.updateAppBadge();
            },
        });
        this.inbox = fields.One("Thread");
        this.starred = fields.One("Thread");
        this.history = fields.One("Thread");
    },
    computeGlobalCounter() {
        return this.inbox?.counter ?? 0;
    },
    async initialize() {
        await Promise.all([
            this.fetchStoreData("failures"),
            this.fetchStoreData("systray_get_activities"),
            super.initialize(...arguments),
        ]);
    },
    onPushNotificationDisplayed() {
        super.onPushNotificationDisplayed(...arguments);
        this.updateAppBadge();
    },
    onStarted() {
        super.onStarted(...arguments);
        this.inbox = {
            display_name: _t("Inbox"),
            id: "inbox",
            model: "mail.box",
        };
        this.starred = {
            display_name: _t("Starred messages"),
            id: "starred",
            model: "mail.box",
        };
        this.history = {
            display_name: _t("History"),
            id: "history",
            model: "mail.box",
        };
        try {
            this.activityBroadcastChannel = new browser.BroadcastChannel(
                "mail.activity.channel",
            );
            this.activityBroadcastChannel.onmessage =
                this._onActivityBroadcastChannelMessage.bind(this);
        } catch {
            this.activityBroadcastChannel = null;
        }
    },
    onUpdateActivityGroups() {},
    /**
     * @param {string} resModel
     * @param {number[]} resIds
     * @param {number|undefined} defaultActivityTypeId
     */
    async scheduleActivity(resModel, resIds, defaultActivityTypeId = undefined) {
        const context = {
            active_model: resModel,
            active_ids: resIds,
            active_id: resIds[0],
            ...(defaultActivityTypeId !== undefined
                ? { default_activity_type_id: defaultActivityTypeId }
                : {}),
        };
        await new Promise((resolve) =>
            this.env.services.action.doAction(
                {
                    type: "ir.actions.act_window",
                    name:
                        resIds && resIds.length > 1
                            ? _t("Schedule Activity On Selected Records")
                            : _t("Schedule Activity"),
                    res_model: "mail.activity.schedule",
                    view_mode: "form",
                    views: [[false, "form"]],
                    target: "new",
                    context,
                },
                {
                    onClose: resolve,
                    additionalContext: {
                        dialog_size: "large",
                    },
                },
            ),
        );
    },
    updateAppBadge() {
        if (unread_store) {
            window.idbKeyval.set("unread", this.globalCounter, unread_store);
            Promise.resolve(navigator.setAppBadge?.(this.globalCounter)).catch(
                () => {},
            );
        }
    },
    /**
     * @param {object} param0
     * @param {{ type: "INSERT"|"DELETE"|"RELOAD_CHATTER", payload: Partial<import("models").Activity> }} param0.data
     */
    _onActivityBroadcastChannelMessage({ data }) {
        switch (data.type) {
            case "INSERT":
                this.insert(data.payload, { broadcast: false });
                break;
            case "DELETE": {
                const activity = this["mail.activity"].insert(data.payload, {
                    broadcast: false,
                });
                activity.remove({ broadcast: false });
                break;
            }
            case "RELOAD_CHATTER": {
                const thread = this.Thread.insert({
                    model: data.payload.model,
                    id: data.payload.id,
                });
                thread.fetchNewMessages();
                thread.fetchThreadData?.(["activities"]);
                break;
            }
        }
    },
    async unstarAll() {
        const starredBox = this.store.starred;
        const messages = starredBox.messages.slice();
        const counterSnapshot = snapshotCounter(starredBox, "counter");
        for (const message of messages) {
            message.starred = false;
        }
        starredBox.counter = 0;
        starredBox.messages = [];
        try {
            await this.env.services.orm.call("mail.message", "unstar_all");
        } catch (error) {
            for (const message of messages) {
                message.starred = true;
            }
            counterSnapshot.restore();
            starredBox.messages = messages;
            throw error;
        }
    },
};
patch(Store.prototype, StorePatch);
