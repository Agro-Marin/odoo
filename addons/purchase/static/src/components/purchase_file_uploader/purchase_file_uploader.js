/** @odoo-module native */
import { DocumentFileUploader } from "@account/components/document_file_uploader/document_file_uploader";
import { WarningDialog } from "@web/components/errors";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { useService } from "@web/core/utils/hooks";

/**
 * Upload vendor bills against one or more purchase orders.
 *
 * Everything about the upload itself — attachment creation, `default_*` context
 * stripping, per-file notifications, markup of server-provided help, navigating
 * to the resulting action — is inherited. Only three things are purchase's own:
 * the model, the method the attachments are handed to, and the single-vendor
 * check below.
 */
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

    /**
     * Purchase creates the bill through ``action_create_invoice_from_file``
     * bound to the selected orders, not through the generic
     * ``create_document_from_attachment`` the account base uses.
     */
    getUploadMethod() {
        return "action_create_invoice_from_file";
    }

    /**
     * `record.resId`, not `record.data.id`: `parseServerValues` drops any server
     * key that is not an active field, so `data.id` resolves only while the
     * purchase order form happens to declare `<field name="id" invisible="1"/>`.
     * `resId` is populated regardless, and this returns a list either way.
     *
     * @returns {Promise<number[]>}
     */
    async getUploadIds() {
        if (this.props.record) {
            return [this.props.record.resId];
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
        }
    }
}

export const purchaseFileUploader = {
    component: PurchaseFileUploader,
};

registry.category("view_widgets").add("purchase_file_uploader", purchaseFileUploader);
