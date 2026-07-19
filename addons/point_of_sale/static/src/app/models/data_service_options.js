/** @odoo-module native */
// This file is just a "static" class to store the options for the DataService class.
// We are now able to override options from others modules
export class DataServiceOptions {
    get databaseTable() {
        // A pos.order is purged from IndexedDB once it is finalized, synced, and
        // belongs to a PAST session. Its children (lines, payments) must follow
        // the SAME predicate on their parent order — otherwise a kept
        // current-session order has its lines/payments purged and reloads as a
        // corrupt header with no lines and a zero total.
        // NB: the JS field is session_id (pos_session_id does not exist on the
        // model — the old clause was always true, so the condition silently
        // degenerated to `finalized && isSynced`).
        const orderIsPurgeable = (order) =>
            Boolean(
                order?.finalized &&
                    order.isSynced &&
                    order.session_id?.id !== parseInt(odoo.pos_session_id),
            );
        return {
            "pos.order": {
                key: "uuid",
                condition: (record) => orderIsPurgeable(record),
            },
            "pos.order.line": {
                key: "uuid",
                condition: (record) => orderIsPurgeable(record.order_id),
            },
            "pos.payment": {
                key: "uuid",
                condition: (record) => orderIsPurgeable(record.pos_order_id),
            },
            "product.attribute.custom.value": {
                key: "id",
                condition: (record) =>
                    record.order_id?.finalized &&
                    typeof record.order_id.id === "number",
            },
        };
    }

    get dynamicModels() {
        return [
            "pos.order",
            "pos.order.line",
            "pos.payment",
            "pos.pack.operation.lot",
            "product.attribute.custom.value",
        ];
    }

    get databaseIndex() {
        const databaseTable = this.databaseTable;
        const indexes = {
            "pos.order": ["uuid"],
            "pos.order.line": ["uuid"],
            "pos.payment": ["uuid"],
            // NB: no "write_date" index — it had zero consumers and a
            // same-second bulk import guarantees collisions on it.
            "product.template": ["pos_categ_ids"],
            "product.product": ["pos_categ_ids", "barcode"],
            "account.fiscal.position": ["tax_ids"],
            "loyalty.program": ["trigger_product_ids"],
            "calendar.event": ["appointment_resource_ids"],
            "res.partner": ["barcode"],
            "product.uom": ["barcode"],
        };

        for (const model in databaseTable) {
            if (!indexes[model]) {
                indexes[model] = [databaseTable[model].key];
            } else if (!indexes[model].includes(databaseTable[model].key)) {
                indexes[model].push(databaseTable[model].key);
            }
        }

        return indexes;
    }

    get autoLoadedOrmMethods() {
        return ["read", "search_read", "create"];
    }

    get prohibitedAutoLoadedModels() {
        return [
            "pos.order", // Cannot be auto-loaded can cause infinite loop
            "pos.order.line", // Cannot be auto-loaded can cause infinite loop
            "pos.session",
            "pos.config",
            "res.users",
            "account.tax", // Cannot be auto-loaded because the record needs adaptions
        ];
    }

    get cascadeDeleteModels() {
        return [
            "pos.order.line",
            "pos.payment",
            "product.attribute.custom.value",
            "pos.pack.operation.lot",
        ];
    }

    get uniqueModels() {
        return ["pos.session", "res.users", "res.company"];
    }

    get cleanupModels() {
        return ["product.template", "product.product"];
    }

    get prohibitedAutoLoadedFields() {
        return {
            "res.partner": ["property_product_pricelist"],
        };
    }
}
