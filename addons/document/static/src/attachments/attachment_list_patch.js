/** @odoo-module native */
import { AttachmentList } from "@mail/core/common/attachment_list";
import { _t } from "@web/core/translation";
import { useService } from "@web/core/utils/hooks";
import { patch } from "@web/core/utils/patch";
import { useMailContext } from "@mail/utils/common/mail_context";

patch(AttachmentList.prototype, {
    setup() {
        super.setup();
        this.mailContext = useMailContext();
        this.dialog = useService("dialog");
        this.documentService = useService("document.document");
        this.notification = useService("notification");
        this.orm = useService("orm");
    },

    /**
     * @param {import("models").Attachment} attachment
     */
    canAddToDocuments(attachment) {
        return (
            this.documentService.userIsDocumentUser &&
            !attachment.uploading &&
            !this.mailContext.inComposer
        );
    },

    getActions(attachment) {
        const res = super.getActions(...arguments);
        if (this.canAddToDocuments(attachment)) {
            res.push({
                label: _t("Add to My Documents"),
                icon: "fa-regular fa-hard-drive",
                onSelect: () => this.onClickAddToDocuments(attachment),
            });
        }
        return res;
    },

    /**
     * @param {import("models").Attachment} attachment
     */
    async onClickAddToDocuments(attachment) {
        const defaults = await this.orm.call(
            "ir.attachment",
            "get_documents_operation_add_destination",
            [attachment.id],
        );
        await this.documentService.openOperationDialog({
            attachmentId: attachment.id,
            operation: "add",
            onClose: () => this.documentService.reload(),
            context: {
                default_destination: defaults.destination,
                default_display_name: defaults.display_name,
            },
        });
    },
});
