// @ts-check
/** @odoo-module native */
/** @typedef {import("./record").Record} Record */
/** @import { RecordList } from "./record_list" */
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

/** @typedef {import("models").MailIdExpression} IdExpression */
/**
 * Raw metadata consumed by ModelInternal before the store replaces a field with its value.
 * @typedef {Object<string | symbol, any>} FieldDefinition
 * @property {boolean} [html]
 * @property {string} [targetModel]
 * @property {unknown} [default]
 * @property {string} [type]
 * @property {string} [inverse]
 * @property {Function} [compute]
 * @property {Function} [onAdd]
 * @property {Function} [onDelete]
 * @property {Function} [onUpdate]
 * @property {Function} [sort]
 */

/**
 * Runtime model fields are registered dynamically; keep their dictionary access
 * inside the model infrastructure rather than widening every public record.
 * @param {Record} record
 * @returns {import("./record").RecordFields}
 */
export function fieldsOf(record) {
    return /** @type {import("./record").RecordFields} */ (
        /** @type {unknown} */ (record)
    );
}

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
 * @param {string | symbol} fieldName
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

/**
 * @template T
 * @typedef {T extends boolean ? boolean : T extends string ? string : T extends number ? number : T} AttributeValue
 */

export const fields = {
    /**
     * @template {string} M
     * @template {Record} [R=Record]
     * @param {M & (string extends M ? unknown : M extends keyof import("models").Models ? unknown : never)} targetModel
     * @param {Object} [param1={}]
     * @param {(this: R) => import("models").MailModel<M> | Partial<import("models").MailModel<M>> | false | null | undefined} [param1.compute]
     * @param {string} [param1.inverse]
     * @param {(this: R, r: import("models").MailModel<M>) => void} [param1.onAdd]
     * @param {(this: R, r: import("models").MailModel<M>) => void} [param1.onDelete]
     * @param {(this: R) => void} [param1.onUpdate]
     * @returns {import("models").MailModel<M>}
     */
    One(targetModel, param1) {
        return /** @type {import("models").MailModel<M>} */ (
            /** @type {unknown} */ ({
                ...param1,
                targetModel,
                [FIELD_DEFINITION_SYM]: true,
                [ONE_SYM]: true,
            })
        );
    },
    /**
     * @template {string} M
     * @template {Record} [R=Record]
     * @param {M & (string extends M ? unknown : M extends keyof import("models").Models ? unknown : never)} targetModel
     * @param {Object} [param1={}]
     * @param {(this: R) => Iterable<import("models").MailModel<M> | Partial<import("models").MailModel<M>>> | null | undefined} [param1.compute]
     * @param {string} [param1.inverse]
     * @param {(this: R, r: import("models").MailModel<M>) => void} [param1.onAdd]
     * @param {(this: R, r: import("models").MailModel<M>) => void} [param1.onDelete]
     * @param {(this: R) => void} [param1.onUpdate]
     * @param {(this: R, r1: import("models").MailModel<M>, r2: import("models").MailModel<M>) => number} [param1.sort]
     * @returns {RecordList<import("models").MailModel<M>>}
     */
    Many(targetModel, param1) {
        return /** @type {RecordList<import("models").MailModel<M>>} */ (
            /** @type {unknown} */ ({
                ...param1,
                targetModel,
                [FIELD_DEFINITION_SYM]: true,
                [MANY_SYM]: true,
            })
        );
    },
    /**
     * @template T
     * @template {Record} [R=Record]
     * @param {T} def
     * @param {Object} [param1={}]
     * @param {(this: R) => NoInfer<AttributeValue<T>>} [param1.compute]
     * @param {(this: R) => void} [param1.onUpdate]
     * @param {(this: R, a: any, b: any) => number} [param1.sort]
     * @param {'datetime'|'date'} [param1.type]
     * @returns {T}
     */
    Attr(def, param1) {
        return /** @type {T} */ (
            /** @type {unknown} */ ({
                ...param1,
                [FIELD_DEFINITION_SYM]: true,
                [ATTR_SYM]: true,
                default: def,
            })
        );
    },
    /**
     * @template {Record} [R=Record]
     * @param {string | import("@odoo/owl").Markup} def
     * @param {Object} [param1={}]
     * @param {(this: R) => string | import("@odoo/owl").Markup | null | undefined} [param1.compute]
     * @param {(this: R) => void} [param1.onUpdate]
     * @returns {string | import("@odoo/owl").Markup}
     */
    Html(def, param1) {
        /** @type {FieldDefinition} */
        const definition = {
            ...param1,
            [FIELD_DEFINITION_SYM]: true,
            [ATTR_SYM]: true,
            default: def,
        };
        definition.html = true;
        return /** @type {string | import("@odoo/owl").Markup} */ (
            /** @type {unknown} */ (definition)
        );
    },
    /**
     * @template {Record} [R=Record]
     * @param {Object} [param0={}]
     * @param {(this: R) => luxon.DateTime | null | undefined} [param0.compute]
     * @param {(this: R) => void} [param0.onUpdate]
     * @returns {luxon.DateTime}
     */
    Date(param0) {
        return /** @type {luxon.DateTime} */ (
            /** @type {unknown} */ ({
                ...param0,
                [FIELD_DEFINITION_SYM]: true,
                [ATTR_SYM]: true,
                type: "date",
            })
        );
    },
    /**
     * @template {Record} [R=Record]
     * @param {Object} [param0={}]
     * @param {(this: R) => luxon.DateTime | null | undefined} [param0.compute]
     * @param {(this: R) => void} [param0.onUpdate]
     * @returns {luxon.DateTime}
     */
    Datetime(param0) {
        return /** @type {luxon.DateTime} */ (
            /** @type {unknown} */ ({
                ...param0,
                [FIELD_DEFINITION_SYM]: true,
                [ATTR_SYM]: true,
                type: "datetime",
            })
        );
    },
};
