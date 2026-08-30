/** @odoo-module native */
import { WebChatter } from "@mail/chatter/web/web_chatter";
import { patch } from "@web/core/utils/patch";
import { onWillStart, onWillUpdateProps, useState } from "@odoo/owl";

/**
 * The supporting document of a time off request also shows up in the chatter,
 * which is the one place it escapes the form view. hr.leave decides who may
 * be shown it -- see attachment_is_visible -- so the chatter has to ask.
 */
const hrLeaveChatterPatch = {
    setup() {
        super.setup();
        this.hrLeave = useState({ hideAttachments: false });
        onWillStart(() => this.loadHrLeaveAttachmentVisibility(this.props));
        onWillUpdateProps((nextProps) => this.loadHrLeaveAttachmentVisibility(nextProps));
    },

    async loadHrLeaveAttachmentVisibility({ threadModel, threadId }) {
        if (threadModel !== "hr.leave" || !threadId) {
            this.hrLeave.hideAttachments = false;
            return;
        }
        const [leave] = await this.orm.read("hr.leave", [threadId], ["attachment_is_visible"]);
        this.hrLeave.hideAttachments = !leave?.attachment_is_visible;
    },

    get attachments() {
        return this.hrLeave.hideAttachments ? [] : super.attachments;
    },
};

patch(WebChatter.prototype, hrLeaveChatterPatch);
