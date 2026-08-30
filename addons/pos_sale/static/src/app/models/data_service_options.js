/** @odoo-module native */
import { DataServiceOptions } from "@point_of_sale/app/models/data_service_options";
import { patch } from "@web/core/utils/patch";
patch(DataServiceOptions.prototype, {
    get databaseTable() {
        // Built lazily from the first record seen and cached for the rest of
        // this sync pass, so both conditions below are an O(1) Set lookup
        // instead of an O(n) scan of pos.order.line per record.
        let linkedSaleOrderIds = null;
        let linkedSaleOrderLineIds = null;
        const ensureLinkedIdsIndexed = (record) => {
            if (linkedSaleOrderIds) {
                return;
            }
            linkedSaleOrderIds = new Set();
            linkedSaleOrderLineIds = new Set();
            for (const line of record.models["pos.order.line"].getAll()) {
                if (line.sale_order_origin_id) {
                    linkedSaleOrderIds.add(line.sale_order_origin_id.id);
                }
                if (line.sale_order_line_id) {
                    linkedSaleOrderLineIds.add(line.sale_order_line_id.id);
                }
            }
        };
        return {
            ...super.databaseTable,
            "sale.order": {
                key: "id",
                condition: (record) => {
                    ensureLinkedIdsIndexed(record);
                    return linkedSaleOrderIds.has(record.id);
                },
            },
            "sale.order.line": {
                key: "id",
                condition: (record) => {
                    ensureLinkedIdsIndexed(record);
                    return linkedSaleOrderLineIds.has(record.id);
                },
            },
        };
    },
});
