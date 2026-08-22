/** @odoo-module native */
import { AccountFileUploader } from "@account/components/account_file_uploader/account_file_uploader";

/**
 * @param {typeof import("@odoo/owl").Component} Base
 */
export const WithAccountFileUploader = (Base) =>
    class extends Base {
        static components = {
            ...Base.components,
            AccountFileUploader,
        };

        setup() {
            super.setup();
            const context = this.props.context;
            this.showUploadButton =
                context.default_move_type !== "entry" || "active_id" in context;
        }
    };
