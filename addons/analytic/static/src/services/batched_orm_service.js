/** @odoo-module native */
import { registry } from "@web/core/registry";
import { unique } from "@web/core/utils/collections/arrays";
import { Deferred } from "@web/core/utils/concurrency";
import { ORM } from "@web/services/orm_service";

class RequestBatcherORM extends ORM {
    constructor() {
        super();
        this.searchReadBatches = {};
        this.searchReadBatchId = 1;
        this.batches = {};
    }

    /**
     * @param {number[]} ids
     * @param {any[]} keys
     * @param {Function} callback
     * @returns {Promise<any>}
     */
    async batch(ids, keys, callback) {
        const key = JSON.stringify(keys);
        let batch = this.batches[key];
        if (!batch) {
            batch = {
                deferred: new Deferred(),
                scheduled: false,
                ids: [],
            };
            this.batches[key] = batch;
        }
        batch.ids = unique([...batch.ids, ...ids]);

        if (!batch.scheduled) {
            batch.scheduled = true;
            Promise.resolve().then(async () => {
                delete this.batches[key];
                let result;
                try {
                    result = await callback(batch.ids);
                } catch (e) {
                    return batch.deferred.reject(e);
                }
                batch.deferred.resolve(result);
            });
        }

        return batch.deferred;
    }

    /**
     * Entry point to batch "read" calls. Calls sharing the same `resModel`,
     * `fields` and `kwargs` and issued before the batch is flushed (next
     * microtask) are merged into a single read; each caller then gets back only
     * the records matching the ids it asked for.
     *
     * @param {string} resModel
     * @param {number[]} resIds
     * @param {string[]} fields
     * @param {Object} kwargs
     * @returns {Promise<Object[]>}
     */
    async read(resModel, resIds, fields, kwargs) {
        const records = await this.batch(
            resIds,
            ["read", resModel, fields, kwargs],
            (resIds) => super.read(resModel, resIds, fields, kwargs),
        );
        return records.filter((r) => resIds.includes(r.id));
    }
}

export const batchedOrmService = {
    async: [
        "call",
        "create",
        "nameGet",
        "read",
        "formattedReadGroup",
        "search",
        "searchRead",
        "unlink",
        "webSearchRead",
        "write",
    ],
    start() {
        return new RequestBatcherORM();
    },
};

registry.category("services").add("batchedOrm", batchedOrmService);
