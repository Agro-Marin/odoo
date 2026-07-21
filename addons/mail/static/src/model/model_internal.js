/** @odoo-module native */
import { ATTR_SYM, MANY_SYM, ONE_SYM } from "./misc.js";

export class ModelInternal {
    /** @type {Map<string, boolean>} */
    fields = new Map();
    /** @type {Map<string, boolean>} */
    fieldsAttr = new Map();
    /** @type {Map<string, boolean>} */
    fieldsOne = new Map();
    /** @type {Map<string, boolean>} */
    fieldsMany = new Map();
    /** @type {Map<string, boolean>} */
    fieldsHtml = new Map();
    /** @type {Map<string, string>} */
    fieldsTargetModel = new Map();
    /** @type {Map<string, () => any>} */
    fieldsCompute = new Map();
    /**
     * Default values of attr fields, interned once per Model at registration
     * so record construction never reads the per-instance definition objects.
     *
     * @type {Map<string, any>}
     */
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
    /**
     * Names of fields participating in the model's id (from `static id`,
     * flattening AND/OR expressions). These fields are immutable once the
     * record is inserted. Populated by `makeStore`.
     *
     * @type {Set<string>}
     */
    idFields = new Set();

    prepareField(fieldName, data) {
        this.fields.set(fieldName, true);
        if (data[ATTR_SYM]) {
            this.fieldsAttr.set(fieldName, true);
        }
        if (data[ONE_SYM]) {
            this.fieldsOne.set(fieldName, true);
        }
        if (data[MANY_SYM]) {
            this.fieldsMany.set(fieldName, true);
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
                    // Unknown options were dropped without a word, so a typo
                    // ("computed", "sortBy", "onUpdated") produced a silently
                    // inert field that no test could catch -- and `eager: true`
                    // accumulated at 16 call sites while meaning nothing (fields
                    // are always eager; see model/store.js). Warn rather than
                    // throw: options may still be passed from addons in other
                    // repos, and breaking their registration at load time is a
                    // worse failure than a console message.
                    console.warn(
                        `Record field ${fieldName}: unknown option "${key}" is ignored.`,
                    );
                }
            }
        }
    }
}
