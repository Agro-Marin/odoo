// @ts-check
/** @odoo-module native */
import { Thread } from "@mail/core/common/thread_model";
import { compareDatetime } from "@mail/utils/common/misc";
import { makeLogger } from "@web/core/debug/debug_logger";
import { rpc } from "@web/core/network";
import { patch } from "@web/core/utils/patch";

import { fields } from "../common/record.js";

const log = makeLogger("mail.thread");
/** @type {Partial<import("models").Thread> & ThisType<import("models").Thread>} */
const threadPatch = {
    setup() {
        super.setup();
        this.recipients = fields.Many("mail.followers");
        this.activities = fields.Many("mail.activity", {
            sort: (a, b) =>
                compareDatetime(a.date_deadline, b.date_deadline) || a.id - b.id,
            onDelete(r) {
                r.remove();
            },
        });
        /** @type {boolean} */
        this.isDisplayedInDiscussAppDesktop = fields.Attr(undefined, {
            /** @this {import("models").Thread} */
            compute() {
                if (
                    this.store.discuss?.isActive &&
                    !this.store.env.services.ui.isSmall
                ) {
                    return this.eq(this.store.discuss.thread);
                }
                return false;
            },
        });
    },
    computeIsDisplayed() {
        return this.isDisplayedInDiscussAppDesktop || super.computeIsDisplayed();
    },
    async loadMoreFollowers() {
        const endLoad = log.perf("loadMoreFollowers");
        const data = await this.store.env.services.orm.call(
            this.model,
            "message_get_followers",
            [[this.id], this.followers.at(-1).id],
        );
        endLoad({ thread: this.localId, models: Object.keys(data || {}) });
        this.store.insert(data);
    },
    /**
     * @param {Object} [options]
     * @returns {boolean|undefined}
     */
    openWebClientUI(options) {
        const actionService = this.store.env.services.action;
        log.logic("openWebClientUI", () => ({
            thread: this.localId,
            isMailbox: this.isMailbox,
            discussActive: this.store.discuss.isActive,
            fromMessagingMenu: options?.fromMessagingMenu,
        }));
        if (this.isMailbox) {
            if (this.store.discuss.isActive) {
                this.setAsDiscussThread();
            } else {
                actionService.doAction({
                    context: { active_id: `mail.box_${this.id}` },
                    tag: "mail.action_discuss",
                    type: "ir.actions.client",
                });
            }
        } else {
            actionService.doAction(this.openRecordActionRequest).catch((error) => {
                log.logic("openRecordAction failed", () => ({
                    thread: this.localId,
                    fromMessagingMenu: options?.fromMessagingMenu,
                    message: error?.message,
                }));
                if (options?.fromMessagingMenu) {
                    this.store.inbox.highlightMessage = this.needactionMessages.at(-1);
                    actionService.doAction({
                        context: { active_id: "mail.box_inbox" },
                        tag: "mail.action_discuss",
                        type: "ir.actions.client",
                    });
                } else {
                    throw error;
                }
            });
        }
        return true;
    },
    get openRecordActionRequest() {
        return {
            type: "ir.actions.act_window",
            res_id: this.id,
            res_model: this.model,
            views: [[false, "form"]],
        };
    },
    async unpin() {
        await this.store.chatHub.initPromise;
        const chatWindow = this.store.ChatWindow.get({ thread: this });
        await chatWindow?.close();
        await super.unpin(...arguments);
    },
    async follow() {
        log.logic("follow", () => ({ thread: this.localId }));
        const data = await rpc("/mail/thread/subscribe", {
            res_model: this.model,
            res_id: this.id,
            partner_ids: [this.store.self_partner.id],
        });
        this.store.insert(data);
    },
};
patch(Thread.prototype, threadPatch);
