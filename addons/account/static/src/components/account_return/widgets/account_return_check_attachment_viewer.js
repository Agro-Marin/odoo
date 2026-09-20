/** @odoo-module native */
import { Component } from "@odoo/owl";
import { useFileViewer } from "@web/components/file_viewer";
import { downloadFile } from "@web/core/network";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardWidgetProps } from "@web/views/widgets";

import { CheckAttachment } from "./account_return_check_attachment_model.js";

class AccountReturnCheckAttachmentViewer extends Component {
    static template = "account.AccountReturnCheckAttachmentViewer";
    static components = {};
    static props = {
        ...standardWidgetProps,
    };

    setup() {
        super.setup();
        this.orm = useService("orm");
        this.fileViewer = useFileViewer();
    }

    async openAttachments() {
        const result = await this.orm.read(
            this.props.record.resModel,
            [this.props.record.resId],
            ["attachment_ids"],
        );
        if (result) {
            const attachmentIds = result[0].attachment_ids;
            const attachmentsData = await this.orm.read(
                "ir.attachment",
                attachmentIds,
                [
                    "access_token",
                    "checksum",
                    "id",
                    "name",
                    "store_fname",
                    "type",
                    "url",
                    "mimetype",
                ],
            );
            const attachments = [];
            for (const attachmentData of attachmentsData) {
                const splittedName = attachmentData.name.split(".");
                const extension = splittedName[splittedName.length - 1];
                attachments.push(
                    new CheckAttachment({
                        ...attachmentData,
                        filename: attachmentData.name,
                        extension: extension,
                    }),
                );
            }
            const viewableFiles = attachments.filter((file) => file.isViewable);
            const unviewableFiles = attachments.filter((file) => !file.isViewable);
            for (const unviewableFile of unviewableFiles) {
                downloadFile(unviewableFile.downloadUrl);
            }
            if (viewableFiles.length) {
                this.fileViewer.open(viewableFiles[0], viewableFiles);
            }
        }
    }
}

export const accountReturnCheckAttachmentViewer = {
    component: AccountReturnCheckAttachmentViewer,
};

registry
    .category("view_widgets")
    .add("account_return_check_attachment_viewer", accountReturnCheckAttachmentViewer);
