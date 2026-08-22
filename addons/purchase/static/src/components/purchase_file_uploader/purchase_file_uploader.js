/** @odoo-module native */
import { DocumentFileUploader } from "@account/components/document_file_uploader/document_file_uploader";
import { WarningDialog } from "@web/components/errors";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
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

    getUploadMethod() {
        return "action_create_invoice_from_file";
    }

    /**
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
