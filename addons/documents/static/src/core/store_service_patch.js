/** @odoo-module native */
import { Store } from "@mail/core/common/store_service";

import { patch } from "@web/core/utils/patch";

patch(Store.prototype, {
    hasDocumentsUserGroup: false,
    setup() {
        super.setup();
        this.Document = {
            /** @type {Object.<number, import("@documents/core/document_model").Document>} */
            records: {},
            /**
             * @param {Object} data
             * @returns {import("@documents/core/document_model").Document}
             */
            insert: (data) => this.env.services["document.document"].insert(data),
        };
    },
});
