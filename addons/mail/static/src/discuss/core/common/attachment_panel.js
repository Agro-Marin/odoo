/** @odoo-module native */
import { ActionPanel } from "@mail/core/common/action_panel";
import { AttachmentList } from "@mail/core/common/attachment_list";
import { DateSection } from "@mail/core/common/date_section";
import { useVisible } from "@mail/utils/common/hooks";
import { makeSequential } from "@mail/utils/common/misc";
import { Component, onWillStart, onWillUpdateProps } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
/**
 * @typedef {Object} Props
 * @property {import("models").Thread} thread
 * @extends {Component<Props, import("@web/env").OdooEnv>}
 */
export class AttachmentPanel extends Component {
    static components = { ActionPanel, AttachmentList, DateSection };
    static props = ["thread"];
    static template = "mail.AttachmentPanel";

    setup() {
        super.setup();
        this.sequential = makeSequential();
        this.store = useService("mail.store");
        this.ormService = useService("orm");
        this.attachmentUploadService = useService("mail.attachment_upload");
        onWillStart(() => {
            this.props.thread.fetchMoreAttachments();
        });
        onWillUpdateProps(
            /** @param {{thread: import("models").Thread}} nextProps */ (nextProps) => {
                if (nextProps.thread.notEq(this.props.thread)) {
                    nextProps.thread.fetchMoreAttachments();
                }
            },
        );
        useVisible(
            "load-older",
            /** @param {boolean} isVisible */ (isVisible) => {
                if (isVisible) {
                    this.props.thread.fetchMoreAttachments();
                }
            },
        );
    }

    /** @return {Object<string, import("models").Attachment[]>} */
    get attachmentsByDate() {
        const attachmentsByDate = {};
        for (const attachment of this.props.thread.attachments) {
            const attachments = attachmentsByDate[attachment.monthYear] ?? [];
            attachments.push(attachment);
            attachmentsByDate[attachment.monthYear] = attachments;
        }
        return attachmentsByDate;
    }
}
