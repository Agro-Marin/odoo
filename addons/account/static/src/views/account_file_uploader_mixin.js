/** @odoo-module native */
import { AccountFileUploader } from "@account/components/account_file_uploader/account_file_uploader";

/**
 * Whether the "Upload" button should be offered on a move list/kanban: always,
 * except on the pure Journal Entries view (default_move_type === "entry") opened
 * without a specific record context.
 *
 * @param {Object} context the controller's props.context
 * @returns {boolean}
 */
export function showAccountUploadButton(context) {
    return context.default_move_type !== "entry" || "active_id" in context;
}

/**
 * Adds the AccountFileUploader to a list/kanban controller's components.
 *
 * @param {typeof import("@web/views/view").ViewController} Base
 */
export const WithAccountFileUploader = (Base) =>
    class extends Base {
        static components = {
            ...Base.components,
            AccountFileUploader,
        };
    };
