// @ts-check
/** @odoo-module native */

import { Component, onWillStart, useState } from "@odoo/owl";
import { FileInput } from "@web/components/file_input/file_input";
import { useService } from "@web/core/utils/hooks";
import { Dialog } from "@web/ui/dialog/dialog";

let nextDialogId = 1;

export class KanbanCoverImageDialog extends Component {
    static template = "web.KanbanCoverImageDialog";
    static components = { Dialog, FileInput };
    static props = {
        record: Object,
        fieldName: String,
        close: Function,
    };
    setup() {
        this.id = `o_cover_image_upload_${nextDialogId++}`;
        this.orm = useService("orm");
        this.http = useService("http");
        const { record, fieldName } = this.props;
        const attachment = record.data[fieldName];
        this.state = useState({
            selectedAttachmentId: attachment?.id || false,
        });
        onWillStart(async () => {
            this.attachments = await this.orm.searchRead(
                "ir.attachment",
                [
                    ["res_model", "=", record.resModel],
                    ["res_id", "=", record.resId],
                    ["mimetype", "ilike", "image"],
                ],
                ["id"],
            );
        });
    }

    /** @returns {boolean} */
    get hasCoverImage() {
        return Boolean(this.props.record.data[this.props.fieldName]);
    }

    /**
     * @param {Object[]} _
     */
    onUpload([attachment]) {
        if (!attachment) {
            return;
        }
        this.selectAttachment(attachment, true);
    }

    /**
     * @param {Record<string, any>} attachment
     * @param {boolean} setSelected
     */
    selectAttachment(attachment, setSelected) {
        if (this.state.selectedAttachmentId !== attachment.id) {
            this.state.selectedAttachmentId = attachment.id;
        } else {
            this.state.selectedAttachmentId = null;
        }
        if (setSelected) {
            this.setCover();
        }
    }

    removeCover() {
        this.state.selectedAttachmentId = null;
        this.setCover();
    }

    async setCover() {
        const value = this.state.selectedAttachmentId
            ? { id: this.state.selectedAttachmentId }
            : false;
        await this.props.record.update(
            { [this.props.fieldName]: value },
            { save: true },
        );
        this.props.close();
    }
}
