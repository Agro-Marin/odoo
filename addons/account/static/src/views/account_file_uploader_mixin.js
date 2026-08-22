/** @odoo-module native */
import { AccountFileUploader } from "@account/components/account_file_uploader/account_file_uploader";

/**
 * Adds the AccountFileUploader to a list/kanban controller, and the flag its
 * button template reads.
 *
 * @param {typeof import("@odoo/owl").Component} Base list/kanban controller to extend.
 */
export const WithAccountFileUploader = (Base) =>
    class extends Base {
        static components = {
            ...Base.components,
            AccountFileUploader,
        };

        setup() {
            super.setup();
            // Hidden only on the Journal Entries view opened without an
            // "active_id" — there is no journal to upload into.
            const context = this.props.context;
            this.showUploadButton =
                context.default_move_type !== "entry" || "active_id" in context;
        }
    };
