/** @odoo-module native */
import {
    deserializeDate,
    deserializeDateTime,
    serializeDate,
    serializeDateTime,
} from "@web/core/l10n/dates";
export const RELATION_TYPES = new Set(["many2many", "many2one", "one2many"]);
export const DATE_TIME_TYPE = new Set(["date", "datetime"]);
export const X2MANY_TYPES = new Set(["many2many", "one2many"]);
export const PARENT_X2MANY_TYPES = new Set(["many2one", "many2many"]);
export const RAW_SYMBOL = Symbol("raw");
export const STORE_SYMBOL = Symbol("store");
export const SERIALIZED_UI_STATE_PROP = "JSONuiState";
export const BACKREF_PREFIX = "<-";

export function getBackRef(model, fieldName) {
    return `${BACKREF_PREFIX}${model}.${fieldName}`;
}
export function clone(obj) {
    return JSON.parse(
        JSON.stringify(obj, (_, value) => (value instanceof Set ? [...value] : value)),
    );
}

/**
 * @param {Object} obj
 * @param {Function} fn
 * @returns {Object}
 */
export function mapObj(obj, fn) {
    return Object.fromEntries(Object.entries(obj).map(([k, v], i) => [k, fn(k, v, i)]));
}

export function convertRawToDateTime(model, value, prop) {
    if (!value) {
        return undefined;
    }
    const datetime = deserializeDateTime(value);
    if (!datetime.isValid) {
        throw new Error(
            `Invalid date: ${value} for model ${model.model} in field ${prop}`,
        );
    }
    return datetime;
}

export function convertDateTimeToRaw(value) {
    if (!value) {
        return undefined;
    }
    if (typeof value !== "string") {
        return serializeDateTime(value);
    }
    return value;
}

export function convertRawToDate(model, value, prop) {
    if (!value) {
        return undefined;
    }
    const date = deserializeDate(value);
    if (!date.isValid) {
        throw new Error(
            `Invalid date: ${value} for model ${model.model} in field ${prop}`,
        );
    }
    return date;
}

export function convertDateToRaw(value) {
    if (!value) {
        return undefined;
    }
    if (typeof value !== "string") {
        return serializeDate(value);
    }
    return value;
}

/**
 * @param {Object|Array} obj
 * @param {string} errorMsg
 * @returns {Proxy}
 */
export function deepImmutable(obj, errorMsg) {
    return new Proxy(obj, {
        get(target, prop, receiver) {
            if ("__deepImmutable" === prop) {
                return true;
            }
            const value = Reflect.get(target, prop, receiver);
            return value && typeof value === "object"
                ? deepImmutable(value, errorMsg)
                : value;
        },
        set() {
            throw new Error(errorMsg);
        },
        deleteProperty() {
            throw new Error(errorMsg);
        },
        defineProperty() {
            throw new Error(errorMsg);
        },
    });
}

export class AggregatedUpdates {
    constructor() {
        this.updates = new Map();
    }

    /**
     * @param {Object} record
     * @param {string} fieldName
     */
    add(record, fieldName) {
        if (!this.updates.has(record)) {
            this.updates.set(record, new Set());
        }
        this.updates.get(record).add(fieldName);
    }

    /**
     * @param {Object} opts
     * @param {string[]} [opts.silentModels=[]]
     */
    fireEventAndDirty(opts = {}) {
        const { silentModels = [] } = opts;
        for (const [record, fields] of this.updates) {
            if (!silentModels.includes(record.model.name)) {
                record.model.triggerEvents("update", {
                    id: record.id,
                    fields: [...fields],
                });
            }
            record._markDirty([...fields]);
        }
    }

    remove(record) {
        this.updates.delete(record);
    }
}
