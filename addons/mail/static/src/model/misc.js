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

export function AND(...args) {
    return [AND_SYM, ...args];
}
export function OR(...args) {
    return [OR_SYM, ...args];
}

const COMMAND_NAMES = new Set(["ADD", "DELETE", "ADD.noinv", "DELETE.noinv"]);
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
 */
export function isOne(Model, fieldName) {
    return Model._.fieldsOne.get(fieldName);
}
/**
 * @param {typeof import("./record").Record} Model
 * @param {string} fieldName
 */
export function isMany(Model, fieldName) {
    return Model._.fieldsMany.get(fieldName);
}
/** @param {Record} record */
export function isRecord(record) {
    return Boolean(record?._?.[IS_RECORD_SYM]);
}
/**
 * @param {typeof import("./record").Record} Model
 * @param {string} fieldName
 */
export function isRelation(Model, fieldName) {
    return isMany(Model, fieldName) || isOne(Model, fieldName);
}
export function isFieldDefinition(val) {
    return val?.[FIELD_DEFINITION_SYM];
}

export const fields = {
    /**
     * @template {keyof import("models").Models} M
     * @param {M} targetModel
     * @param {Object} [param1={}]
     * @param {(this: Record) => any} [param1.compute] if set, the value of this relational field is declarative and
     *   is computed automatically: it is recomputed whenever one of its dependencies changes
     *   (record insertion included). The context of the function is the record. Returned value is new value assigned to this field.
     * @param {string} [param1.inverse] if set, the name of field in targetModel that acts as the inverse.
     * @param {(this: Record, r: import("models").Models[M]) => void} [param1.onAdd] function that is called when a record is added
     *   in the relation.
     * @param {(this: Record, r: import("models").Models[M]) => void} [param1.onDelete] function that is called when a record is removed
     *   from the relation.
     * @param {(this: Record) => void} [param1.onUpdate] function that is called when the field value is updated.
     *   This is called at least once at record creation.
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
     * @param {M} targetModel
     * @param {Object} [param1={}]
     * @param {(this: Record) => any} [param1.compute] if set, the value of this relational field is declarative and
     *   is computed automatically: it is recomputed whenever one of its dependencies changes
     *   (record insertion included). The context of the function is the record. Returned value is new value assigned to this field.
     * @param {string} [param1.inverse] if set, the name of field in targetModel that acts as the inverse.
     * @param {(this: Record, r: import("models").Models[M]) => void} [param1.onAdd] function that is called when a record is added
     *   in the relation.
     * @param {(this: Record, r: import("models").Models[M]) => void} [param1.onDelete] function that is called when a record is removed
     *   from the relation.
     * @param {(this: Record) => void} [param1.onUpdate] function that is called when the field value is updated.
     *   This is called at least once at record creation.
     * @param {(this: Record, r1: import("models").Models[M], r2: import("models").Models[M]) => number} [param1.sort] if defined, this field
     *   is automatically sorted by this function.
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
     * @param {T} def
     * @param {Object} [param1={}]
     * @param {(this: Record) => any} [param1.compute] if set, the value of this attr field is declarative and
     *   is computed automatically: it is recomputed whenever one of its dependencies changes
     *   (record insertion included). The context of the function is the record. Returned value is new value assigned to this field.
     * @param {(this: Record) => void} [param1.onUpdate] function that is called when the field value is updated.
     *   This is called at least once at record creation.
     * @param {(this: Record, Object, Object) => number} [param1.sort] if defined, this field is automatically sorted
     *   by this function.
     * @param {'datetime'|'date'} [param1.type] if defined, automatically transform to a
     * specific type.
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
     * HTML fields are ATTR that are automatically markup when the data being inserted is a markup.
     *
     * @param {string} def
     * @param {Object} [param1={}]
     * @param {(this: Record) => any} [param1.compute] if set, the value of this html field is declarative and
     *   is computed automatically: it is recomputed whenever one of its dependencies changes
     *   (record insertion included). The context of the function is the record. Returned value is new value assigned to this field.
     * @param {(this: Record) => void} [param1.onUpdate] function that is called when the field value is updated.
     *   This is called at least once at record creation.
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
     * @param {Object} [param0={}]
     * @param {(this: Record) => any} [param0.compute] if set, the value of this date field is declarative and
     *   is computed automatically: it is recomputed whenever one of its dependencies changes
     *   (record insertion included). The context of the function is the record. Returned value is new value assigned to this field.
     * @param {(this: Record) => void} [param0.onUpdate] function that is called when the field value is updated.
     *   This is called at least once at record creation.
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
     * @param {Object} [param0={}]
     * @param {(this: Record) => any} [param0.compute] if set, the value of this datetime field is declarative and
     *   is computed automatically: it is recomputed whenever one of its dependencies changes
     *   (record insertion included). The context of the function is the record. Returned value is new value assigned to this field.
     * @param {(this: Record) => void} [param0.onUpdate] function that is called when the field value is updated.
     *   This is called at least once at record creation.
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
