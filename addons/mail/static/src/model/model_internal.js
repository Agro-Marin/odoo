/** @odoo-module native */
import { ATTR_SYM, MANY_SYM, ONE_SYM } from "./misc.js";

export class ModelInternal {
    /** @type {Map<string, ATTR_SYM|ONE_SYM|MANY_SYM>} */
    fields = new Map();
    /** @type {Map<string, boolean>} */
    fieldsHtml = new Map();
    /** @type {Map<string, string>} */
    fieldsTargetModel = new Map();
    /** @type {Map<string, () => any>} */
    fieldsCompute = new Map();
    /** @type {Map<string, any>} */
    fieldsDefault = new Map();
    /** @type {Map<string, string>} */
    fieldsInverse = new Map();
    /** @type {Map<string, () => void>} */
    fieldsOnAdd = new Map();
    /** @type {Map<string, () => void>} */
    fieldsOnDelete = new Map();
    /** @type {Map<string, () => void>} */
    fieldsOnUpdate = new Map();
    /** @type {Map<string, () => number>} */
    fieldsSort = new Map();
    /** @type {Map<string, string>} */
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
