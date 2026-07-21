/** @odoo-module native */
import { AccountFileUploader } from "@account/components/account_file_uploader/account_file_uploader";

/**
 * Whether the "Upload" button should be shown on a move list/kanban. It is
 * hidden only on the Journal Entries view opened without an "active_id".
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
 * @param {typeof import("@odoo/owl").Component} Base list/kanban controller to extend.
 */
export const WithAccountFileUploader = (Base) =>
    class extends Base {
        static components = {
            ...Base.components,
            AccountFileUploader,
        };
    };
