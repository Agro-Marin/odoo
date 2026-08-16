/** @odoo-module native */
/** @typedef {import("./record").Record} Record */
/** @typedef {import("./record_list").RecordList} RecordList */
/** @typedef {import("@web/core/l10n/luxon").luxon} luxon */

import { registry } from "@web/core/registry";
export const modelRegistry = registry.category("discuss.model");

export const FIELD_DEFINITION_SYM = Symbol("field_definition");
/** @typedef {ATTR_SYM|MANY_SYM|ONE_SYM} FIELD_SYM */
export const ATTR_SYM = Symbol("attr");
export const MANY_SYM = Symbol("many");
export const ONE_SYM = Symbol("one");
export const OR_SYM = Symbol("or");
const AND_SYM = Symbol("and");
export const IS_RECORD_SYM = Symbol("isRecord");
export const IS_DELETED_SYM = Symbol("isDeleted");
export const STORE_SYM = Symbol("store");

/**
 * @typedef {string|[typeof AND_SYM|typeof OR_SYM, ...IdExpression[]]} IdExpression
 */

/**
 * @param {...IdExpression} args
 * @returns {IdExpression}
 */
export function AND(...args) {
    return [AND_SYM, ...args];
}
/**
 * @param {...IdExpression} args
 * @returns {IdExpression}
 */
export function OR(...args) {
    return [OR_SYM, ...args];
}

/** @type {Set<string>} */
const COMMAND_NAMES = new Set(["ADD", "DELETE", "ADD.noinv", "DELETE.noinv"]);
/**
 * @param {*} data
 * @returns {boolean}
 * @throws {Error}
 */
export function isCommand(data) {
    if (!Array.isArray(data) || data.length === 0) {
        return false;
    }
    let commandCount = 0;
    for (const entry of data) {
        if (Array.isArray(entry) && COMMAND_NAMES.has(entry[0])) {
            commandCount++;
        }
    }
    if (commandCount === 0) {
        return false;
    }
    if (commandCount === data.length) {
        return true;
    }
    throw new Error(
        `Cannot mix command entries (e.g. ["ADD", ...]) with plain values in relational field data: got ${commandCount} command(s) among ${data.length} entries.`,
    );
}
/**
 * @param {typeof import("./record").Record} Model
 * @param {string} fieldName
 * @returns {boolean}
 */
export function isOne(Model, fieldName) {
    return Model._.fields.get(fieldName) === ONE_SYM;
}
/**
 * @param {typeof import("./record").Record} Model
 * @param {string} fieldName
 * @returns {boolean}
 */
export function isMany(Model, fieldName) {
    return Model._.fields.get(fieldName) === MANY_SYM;
}
/**
 * @param {unknown} record
 * @returns {record is Record}
 */
export function isRecord(record) {
    return Boolean(
        /** @type {{_?: {[IS_RECORD_SYM]?: unknown}}} */ (record)?._?.[IS_RECORD_SYM],
    );
}
/**
 * @param {typeof import("./record").Record} Model
 * @param {string} fieldName
 * @returns {boolean}
 */
export function isRelation(Model, fieldName) {
    const kind = Model._.fields.get(fieldName);
    return kind === ONE_SYM || kind === MANY_SYM;
}
/**
 * @param {*} val
 * @returns {boolean}
 */
export function isFieldDefinition(val) {
    return val?.[FIELD_DEFINITION_SYM];
}

export const fields = {
    /**
     * @template {keyof import("models").Models} M
     * @template {Record} [R=Record] the record owning this field; inferred from
     * @param {M} targetModel
     * @param {Object} [param1={}]
     * @param {(this: R) => any} [param1.compute]
     * @param {string} [param1.inverse]
     * @param {(this: R, r: import("models").Models[M]) => void} [param1.onAdd]
     * @param {(this: R, r: import("models").Models[M]) => void} [param1.onDelete]
     * @param {(this: R) => void} [param1.onUpdate]
     * @returns {import("models").Models[M]}
     */
    One(targetModel, param1) {
        return {
            ...param1,
            targetModel,
            [FIELD_DEFINITION_SYM]: true,
            [ONE_SYM]: true,
        };
    },
    /**
     * @template {keyof import("models").Models} M
     * @template {Record} [R=Record] the record owning this field; inferred from
     * @param {M} targetModel
     * @param {Object} [param1={}]
     * @param {(this: R) => any} [param1.compute]
     * @param {string} [param1.inverse]
     * @param {(this: R, r: import("models").Models[M]) => void} [param1.onAdd]
     * @param {(this: R, r: import("models").Models[M]) => void} [param1.onDelete]
     * @param {(this: R) => void} [param1.onUpdate]
     * @param {(this: R, r1: import("models").Models[M], r2: import("models").Models[M]) => number} [param1.sort]
     * @returns {import("models").Models[M][]}
     */
    Many(targetModel, param1) {
        return {
            ...param1,
            targetModel,
            [FIELD_DEFINITION_SYM]: true,
            [MANY_SYM]: true,
        };
    },
    /**
     * @template T
     * @template {Record} [R=Record] the record owning this field; inferred from
     * @param {T} def
     * @param {Object} [param1={}]
     * @param {(this: R) => any} [param1.compute]
     * @param {(this: R) => void} [param1.onUpdate]
     * @param {(this: R, a: any, b: any) => number} [param1.sort]
     * @param {'datetime'|'date'} [param1.type]
     * @returns {T}
     */
    Attr(def, param1) {
        return {
            ...param1,
            [FIELD_DEFINITION_SYM]: true,
            [ATTR_SYM]: true,
            default: def,
        };
    },
    /**
     * @template {Record} [R=Record] the record owning this field; inferred from
     * @param {string} def
     * @param {Object} [param1={}]
     * @param {(this: R) => any} [param1.compute]
     * @param {(this: R) => void} [param1.onUpdate]
     * @returns {string|markup }
     */
    Html(def, param1) {
        const definition = {
            ...param1,
            [FIELD_DEFINITION_SYM]: true,
            [ATTR_SYM]: true,
            default: def,
        };
        definition.html = true;
        return definition;
    },
    /**
     * @template {Record} [R=Record] the record owning this field; inferred from
     * @param {Object} [param0={}]
     * @param {(this: R) => any} [param0.compute]
     * @param {(this: R) => void} [param0.onUpdate]
     * @returns {luxon.DateTime}
     */
    Date(param0) {
        return {
            ...param0,
            [FIELD_DEFINITION_SYM]: true,
            [ATTR_SYM]: true,
            type: "date",
        };
    },
    /**
     * @template {Record} [R=Record] the record owning this field; inferred from
     * @param {Object} [param0={}]
     * @param {(this: R) => any} [param0.compute]
     * @param {(this: R) => void} [param0.onUpdate]
     * @returns {luxon.DateTime}
     */
    Datetime(param0) {
        return {
            ...param0,
            [FIELD_DEFINITION_SYM]: true,
            [ATTR_SYM]: true,
            type: "datetime",
        };
    },
};
