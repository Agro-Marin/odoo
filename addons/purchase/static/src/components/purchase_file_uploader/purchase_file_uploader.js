/** @odoo-module native */
import { DocumentFileUploader } from "@account/components/document_file_uploader/document_file_uploader";
import { markup } from "@odoo/owl";
import { WarningDialog } from "@web/components/errors/error_dialogs";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class PurchaseFileUploader extends DocumentFileUploader {
    static template = "purchase.DocumentFileUploader";
    static props = {
        ...DocumentFileUploader.props,
        list: { type: Object, optional: true },
    };

    setup() {
        super.setup();
        this.dialog = useService("dialog");
    }

    getResModel() {
        return "purchase.order";
    }

    async getIds() {
        if (this.props.record) {
            return this.props.record.data.id;
        }
        return this.props.list.getResIds(true);
    }

    onClick(ev) {
        if (this.env.config.viewType !== "list") {
            return;
        }
        const vendorSet = new Set(
            this.props.list.selection.map((record) => record.data.partner_id.id),
        );
        if (vendorSet.size > 1) {
            this.dialog.add(WarningDialog, {
                title: _t("Validation Error"),
                message: _t(
                    "You can only upload a bill for a single vendor at a time.",
                ),
            });
            return false;
        }
    }

    /**
     * Purchase creates the vendor bill through ``action_create_invoice_from_file``
     * (bound to the selected order ids as ``self``) rather than the generic
     * ``create_document_from_attachment`` used by the account base. Attachment
     * creation, ``default_*`` context cleaning and notification/markup handling
     * are all inherited from :class:`DocumentFileUploader`.
     */
    async onUploadComplete() {
        const ids = await this.getIds();
        let action;
        try {
            action = await this.orm.call(
                this.getResModel(),
                "action_create_invoice_from_file",
                [ids, this.attachmentIdsToProcess],
                { context: { ...this.extraContext, ...this.env.searchModel.context } },
            );
        } finally {
            // ensures attachments are cleared on success as well as on error
            this.attachmentIdsToProcess = [];
        }
        // Mirror the account base: surface any per-file notifications and render
        // server-provided help as markup before navigating to the action.
        if (action.context?.notifications) {
            for (const [file, msg] of Object.entries(action.context.notifications)) {
                this.notification.add(msg, { title: file, type: "info", sticky: true });
            }
            delete action.context.notifications;
        }
        if (action.help?.length) {
            action.help = markup(action.help);
        }
        this.action.doAction(action);
    }
}

export const purchaseFileUploader = {
    component: PurchaseFileUploader,
};

registry.category("view_widgets").add("purchase_file_uploader", purchaseFileUploader);
