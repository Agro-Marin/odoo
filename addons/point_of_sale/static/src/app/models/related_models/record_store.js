/** @odoo-module native */
import { reactive, toRaw } from "@odoo/owl";

import { Base } from "./base.js";
import { RAW_SYMBOL } from "./utils.js";

export class RecordStore {
    /**
     * @param {Array<string>} models
     * @param {object} indexes
     */
    constructor(models, indexes = {}) {
        this.indexes = {};
        this.records = new Map();

        models.forEach((model) => {
            const modelMap = new Map();
            this.records.set(model, modelMap);
            const indexKeys = new Set([
                ...(indexes[model] || []).filter((s) => s),
                "id",
            ]);
            this.indexes[model] = indexKeys;
            for (const key of indexKeys) {
                modelMap.set(key, new Map());
            }
        });
        return reactive(this);
    }

    /**
     * @param {Base} record
     */
    add(record) {
        return this._updateIndex(record, (map, key, record, isArray = false) => {
            if (isArray) {
                if (!map.has(key)) {
                    map.set(key, new Map([[record.id, record]]));
                } else {
                    map.get(key).set(record.id, record);
                }
            } else {
                map.set(key, record);
            }
        });
    }

    /**
     * @param {Base} record
     */
    remove(record) {
        this._updateIndex(record, (map, key, record, isArray = false) => {
            if (isArray) {
                map.get(key)?.delete(record.id);
            } else if (toRaw(map.get(key)) === toRaw(record)) {
                map.delete(key);
            }
        });
    }

    _updateIndex(record, operation) {
        if (!(record instanceof Base)) {
            throw new Error("Only instances of Base are supported");
        }
        const model = record.model.name;
        this.indexes[model].forEach((index) => {
            const indexValue = record[RAW_SYMBOL][index];
            if (!indexValue) {
                return;
            }
            const map = this.getRecordsMap(model, index);
            if (indexValue instanceof Set) {
                for (const value of indexValue) {
                    if (value) {
                        operation(map, value, record, true);
                    }
                }
            } else {
                operation(map, indexValue, record);
            }
        });
        return this.getById(model, record.id);
    }

    /**
     * @param {string} model
     * @param {string} index
     * @param {*} value
     * @returns {Base| Array<Base>|undefined}
     */
    get(model, index, value) {
        const result = this.getRecordsMap(model, index).get(value);
        return result instanceof Map ? [...result.values()] : result;
    }

    /**
     * @param {string} model
     * @param {*} id
     * @returns {Base|undefined}
     */
    getById(model, id) {
        return this.getRecordsMap(model, "id").get(id);
    }

    /**
     * @param {string} model
     * @param {Array<Base>} -
     */
    getOrderedRecords(model) {
        return Array.from(this.getRecordsMap(model, "id").values());
    }

    /**
     * @param {string} model
     * @param {string} index
     * @param {object} -
     */
    getRecordsByIds(model, index = "id") {
        const indexMap = this.getRecordsMap(model, index);
        if (
            index !== "id" &&
            indexMap.get(indexMap.keys().next().value) instanceof Map
        ) {
            return Object.fromEntries(
                [...indexMap].map(([key, value]) => [key, Array.from(value.values())]),
            );
        }
        return Object.fromEntries(indexMap);
    }

    getRecordsIds(model) {
        return Array.from(this.getRecordsMap(model, "id").keys());
    }

    /**
     * @param {string} model
     * @param {string} index
     * @returns {number}
     */
    getRecordCount(model, index = "id") {
        return this.getRecordsMap(model, index).size;
    }

    /**
     * @param {string} model
     * @param {string} index
     * @returns {boolean}
     */
    hasIndex(model, index) {
        return this.indexes[model]?.has(index) || false;
    }

    getRecordsMap(model, index = "id") {
        const map = this.records.get(model)?.get(index);
        if (!map) {
            throw new Error(`Index '${index}' not defined for model '${model}'`);
        }
        return map;
    }
}
