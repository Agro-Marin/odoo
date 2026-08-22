/** @odoo-module native */
import { rpc } from "@web/core/network";
import { _t } from "@web/core/translation";
import { RelationalModel, RelationalRecord } from "@web/model/relational_model";

class ProductCatalogRecord extends RelationalRecord {
    setup(config, data, options = {}) {
        this.productCatalogData = data.productCatalogData;
        data = { ...data };
        delete data.productCatalogData;
        super.setup(config, data, options);
    }
}

export class ProductCatalogKanbanModel extends RelationalModel {
    static Record = ProductCatalogRecord;
    static withCache = false;

    async _loadData(params) {
        // The sample ORM is installed for the duration of the sample load, so
        // this has to be read before awaiting super.
        const isSample = Boolean(this.orm.isSample);
        const result = await super._loadData(...arguments);
        if (params.isMonoRecord) {
            return result;
        }

        const records = params.groupBy?.length
            ? this._collectGroupedRecords(result.groups)
            : result.records;
        if (!records.length) {
            // Nothing to describe -- the route would answer {} for an empty id
            // list, so the round trip is pure latency.
            return result;
        }

        const productIds = records.map((record) => record.id);
        const orderLinesInfo = isSample
            ? this._getSampleOrderLineInfo(productIds)
            : await rpc(
                  "/product/catalog/order_lines_info",
                  this._getOrderLinesInfoParams(params, productIds),
              );
        for (const record of records) {
            record.productCatalogData = orderLinesInfo[record.id];
        }
        return result;
    }

    /**
     * Flatten the records held by an opened (sub)group tree.
     *
     * @param {Object[]} [groups] as returned by web_read_group
     * @returns {Object[]}
     */
    _collectGroupedRecords(groups = []) {
        const records = [];
        const stack = [...groups];
        while (stack.length) {
            const group = stack.pop();
            if (group.groups?.length) {
                stack.push(...group.groups);
            }
            if (group.records?.length) {
                records.push(...group.records);
            }
        }
        return records;
    }

    _getOrderLinesInfoParams(params, productIds) {
        return {
            order_id: params.context.order_id,
            product_ids: productIds,
            res_model: params.context.product_catalog_order_model,
            child_field: params.context.child_field,
        };
    }

    /**
     * Stand in for `/product/catalog/order_lines_info` when the view runs on
     * sample data (no product matched, so there is no order line to read).
     *
     * Keyed by the ids actually loaded rather than by a fixed range: a grouped
     * sample read hands out ids across the whole generated set, not just the
     * first page of it, and a record with no entry here takes the card template
     * down with it.
     *
     * Values are derived from the id rather than drawn at random so a rendered
     * sample card is reproducible, and are limited to the props this module's
     * `ProductCatalogOrderLine` declares -- fields owned by a downstream order
     * line (`min_qty`, `suggested_qty`, ...) are that module's to supply.
     *
     * @param {number[]} productIds
     * @returns {Object}
     */
    _getSampleOrderLineInfo(productIds) {
        const sampleOrderLineInfo = {};
        for (const productId of productIds) {
            sampleOrderLineInfo[productId] = {
                isSample: true,
                quantity: (productId * 3) % 10,
                price: 100 + ((productId * 37) % 400),
                productType: "consu",
                readOnly: false,
                uomDisplayName: _t("Units"),
            };
        }
        return sampleOrderLineInfo;
    }
}
