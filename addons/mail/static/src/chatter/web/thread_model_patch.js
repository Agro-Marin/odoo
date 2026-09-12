// @ts-check
/** @odoo-module native */
import "@mail/chatter/web_portal/thread_model_patch";

import { fields } from "@mail/core/common/record";
import { Thread } from "@mail/core/common/thread_model";
import { compareDatetime } from "@mail/utils/common/misc";
import { makeLogger } from "@web/core/debug/debug_logger";
import { patch } from "@web/core/utils/patch";

const log = makeLogger("mail.thread");
/** @type {Partial<import("models").Thread> & ThisType<import("models").Thread>} */
const threadPatch = {
    setup() {
        super.setup();
        this.scheduledMessages = fields.Many("mail.scheduled.message", {
            sort: (a, b) =>
                compareDatetime(a.scheduled_date, b.scheduled_date) || a.id - b.id,
            inverse: "thread",
        });
    },

    /** @param {string[]} requestList */
    async fetchThreadData(requestList) {
        const loadsAttachments = requestList.includes("attachments");
        this.isLoadingAttachments = this.isLoadingAttachments || loadsAttachments;
        try {
            await super.fetchThreadData(requestList);
        } catch (error) {
            if (loadsAttachments) {
                this.isLoadingAttachments = false;
            }
            throw error;
        }
        if (
            !this.message_main_attachment_id &&
            this.attachmentsInWebClientView.length > 0
        ) {
            log.logic("default main attachment", () => ({
                thread: this.localId,
                attachments: this.attachmentsInWebClientView.length,
            }));
            this.setMainAttachmentFromIndex(0);
        }
    },
};
patch(Thread.prototype, threadPatch);
