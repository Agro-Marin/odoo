/** @odoo-module native */
import { Store } from "@mail/core/common/store_service";

import { patch } from "@web/core/utils/patch";

patch(Store.prototype, {
    hasDocumentsUserGroup: false,
    setup() {
        super.setup();
        // An own property, not a patch property: a patch property lives on
        // `Store.prototype`, so every store instance would share one `records`
        // map and previewed documents would accumulate across stores.
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
