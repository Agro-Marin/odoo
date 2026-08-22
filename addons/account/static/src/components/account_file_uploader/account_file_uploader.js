/** @odoo-module native */
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";

import { DocumentFileUploader } from "../document_file_uploader/document_file_uploader.js";
import { defaultMoveTypeForJournal } from "../document_file_uploader/journal_defaults.js";

export class AccountFileUploader extends DocumentFileUploader {
    static template = "account.AccountFileUploader";
    static props = {
        ...DocumentFileUploader.props,
        btnClass: { type: String, optional: true },
        linkText: { type: String, optional: true },
        togglerTemplate: { type: String, optional: true },
    };

    getExtraContext() {
        const extraContext = super.getExtraContext();
        const record_data = this.props.record ? this.props.record.data : false;
        return record_data
            ? {
                  ...extraContext,
                  default_journal_id: record_data.id,
                  default_move_type: defaultMoveTypeForJournal(record_data.type),
              }
            : extraContext;
    }

    getResModel() {
        return "account.journal";
    }
}

export const accountFileUploader = {
    component: AccountFileUploader,
    extractProps: ({ attrs }) => ({
        togglerTemplate: attrs.template || "account.JournalUploadLink",
        btnClass: attrs.btnClass || "",
        linkText: attrs.title || _t("Upload"),
    }),
    fieldDependencies: [
        { name: "id", type: "integer" },
        { name: "type", type: "selection" },
    ],
};

registry.category("view_widgets").add("account_file_uploader", accountFileUploader);
