/** @odoo-module native */
import { Store } from "@mail/core/common/store_service";

import { patch } from "@web/core/utils/patch";

patch(Store.prototype, {
    hasDocumentsUserGroup: false,
    setup() {
        super.setup();
        // Built per store instance, deliberately.
        //
        // `Document` used to be declared as a patch property, which put it --
        // and the `records` map inside it -- on `Store.prototype`. Every store
        // instance therefore shared one `records` map, so previewed documents
        // accumulated across stores and leaked between tests. Its `insert` also
        // reached the service through a module-level `let self` assigned in
        // `setup`, i.e. whichever store was constructed last -- the wrong one as
        // soon as two exist.
        //
        // An own property shadows the prototype for every reader
        // (`store.Document.…`), so no call site changes.
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
