/** @odoo-module native */
import { DataServiceOptions } from "@point_of_sale/app/models/data_service_options";
import { patch } from "@web/core/utils/patch";
import { session } from "@web/session";

patch(DataServiceOptions.prototype, {
    // Self-order persists nothing to IndexedDB outside mobile mode, so it uses a
    // minimal databaseTable. This override only applies inside the self-order
    // app (the only context that populates `session.data`): the whole patch is
    // co-loaded into web.assets_unit_tests_setup, so outside a self-order
    // session it must defer to the base table — otherwise it clobbers the
    // entries every other POS module (pos_restaurant, pos_loyalty, …) and the
    // base itself register, which their unit tests depend on.
    get databaseTable() {
        if (!session.data) {
            return super.databaseTable;
        }
        return {
            "pos.order": {
                key: "uuid",
                condition: (record) => false,
            },
            "pos.order.line": {
                key: "uuid",
                condition: (record) => false,
            },
            "pos.payment": {
                key: "uuid",
                condition: (record) => false,
            },
            "pos.payment.method": {
                key: "id",
                condition: (record) => false,
            },
        };
    },
});
