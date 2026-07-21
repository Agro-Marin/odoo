/** @odoo-module native */
import { BillGuide } from "@account/components/bill_guide/bill_guide";

import { FileUploadListRenderer } from "../file_upload_list/file_upload_list_renderer.js";

export class AccountUploadListRenderer extends FileUploadListRenderer {
    static template = "account.AccountUploadListRenderer";
    static components = {
        ...FileUploadListRenderer.components,
        BillGuide,
    };

    // Highlight the ref cell of a record having duplicates: danger for an exact duplicate,
    // warning for a draft.
    getCellClass(column, record) {
        const classNames = super.getCellClass(column, record);
        if (
            column.name === "ref" &&
            record.data.duplicated_ref_ids &&
            record.data.duplicated_ref_ids.count !== 0
        ) {
            if (record.data.is_exact_move_duplicate) {
                return `${classNames} table-danger`;
            } else if (record.data.state === "draft") {
                return `${classNames} table-warning`;
            }
        }
        return classNames;
    }
}
