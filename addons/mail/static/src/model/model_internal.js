// @ts-check
/** @odoo-module native */
import { ATTR_SYM, MANY_SYM, ONE_SYM } from "./misc.js";

/**
 * Metadata has string field names, while proxy lookups can also supply symbols.
 * @template V
 * @typedef {Map<string, V> & Pick<Map<string | symbol, V>, "get" | "has">} FieldMap
 */
export class ModelInternal {
    /** @type {FieldMap< ATTR_SYM|ONE_SYM|MANY_SYM>} */
    fields = new Map();
    /** @type {FieldMap< boolean>} */
    fieldsHtml = new Map();
    /** @type {FieldMap< string>} */
    fieldsTargetModel = new Map();
    /** @type {FieldMap< () => any>} */
    fieldsCompute = new Map();
    /** @type {FieldMap< any>} */
    fieldsDefault = new Map();
    /** @type {FieldMap< string>} */
    fieldsInverse = new Map();
    /** @type {FieldMap< (record: import("./record").Record) => void>} */
    fieldsOnAdd = new Map();
    /** @type {FieldMap< (record: import("./record").Record) => void>} */
    fieldsOnDelete = new Map();
    /** @type {FieldMap< () => void>} */
    fieldsOnUpdate = new Map();
    /** @type {FieldMap< () => number>} */
    fieldsSort = new Map();
    /** @type {FieldMap< string>} */
    fieldsType = new Map();
    /** @type {Set<string>} */
    idFields = new Set();

    /**
     * @param {string} fieldName
     * @param {Object} data
     */
    prepareField(fieldName, data) {
        if (data[ONE_SYM]) {
            this.fields.set(fieldName, ONE_SYM);
        } else if (data[MANY_SYM]) {
            this.fields.set(fieldName, MANY_SYM);
        } else {
            this.fields.set(fieldName, ATTR_SYM);
        }
        for (const key in data) {
            const value = data[key];
            switch (key) {
                case "html": {
                    if (!value) {
                        break;
                    }
                    this.fieldsHtml.set(fieldName, value);
                    break;
                }
                case "targetModel": {
                    this.fieldsTargetModel.set(fieldName, value);
                    break;
                }
                case "compute": {
                    this.fieldsCompute.set(fieldName, value);
                    break;
                }
                case "default": {
                    this.fieldsDefault.set(fieldName, value);
                    break;
                }
                case "sort": {
                    this.fieldsSort.set(fieldName, value);
                    break;
                }
                case "inverse": {
                    this.fieldsInverse.set(fieldName, value);
                    break;
                }
                case "onAdd": {
                    this.fieldsOnAdd.set(fieldName, value);
                    break;
                }
                case "onDelete": {
                    this.fieldsOnDelete.set(fieldName, value);
                    break;
                }
                case "onUpdate": {
                    this.fieldsOnUpdate.set(fieldName, value);
                    break;
                }
                case "type": {
                    this.fieldsType.set(fieldName, value);
                    break;
                }
                default: {
                    console.warn(
                        `Record field ${fieldName}: unknown option "${key}" is ignored.`,
                    );
                }
            }
        }
    }
}
