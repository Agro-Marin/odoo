/** @odoo-module native */
import { Base } from "./base.js";
import {
    convertRawToDate,
    convertRawToDateTime,
    DATE_TIME_TYPE,
    RAW_SYMBOL,
    RELATION_TYPES,
    STORE_SYMBOL,
    X2MANY_TYPES,
} from "./utils.js";

// Records, per record class, the field names whose getter/setter THIS module
// installed on the prototype. Field getters are defined ADDITIVELY across
// createRelatedModels() calls: a record class is a module-level singleton (from
// the `pos_available_models` registry) reused by every store, so it must carry
// the UNION of every store's fields — a store that loads a reduced field set
// (e.g. the preparation display, which drops `taxes_id`/`product_variant_ids`)
// must not permanently strip getters a later full-POS store needs. Tracking our
// own getters lets a re-process add the missing ones while still rejecting a
// field name that collides with an author-defined class member (own or
// inherited), which a bare `in ...prototype` check could not tell apart.
const OWN_FIELD_GETTERS = new WeakMap();

/**
 * Processes model definitions to dynamically define getter and setter properties
 * on model fields, providing controlled access to the raw data.
 */
export function processModelClasses(modelDefs, modelClasses = {}) {
    const modelNames = new Set(Object.keys(modelDefs));
    for (const modelName of modelNames) {
        const fields = modelDefs[modelName];
        const ModelRecordClass =
            modelClasses[modelName] || class ModelRecord extends Base {};

        // Always register the class for this call, even if its prototype was
        // already processed in a previous call — otherwise _create() would later
        // do `new undefined`.
        modelClasses[modelName] = ModelRecordClass;

        let ownGetters = OWN_FIELD_GETTERS.get(ModelRecordClass);
        if (!ownGetters) {
            ownGetters = new Set();
            OWN_FIELD_GETTERS.set(ModelRecordClass, ownGetters);
        }

        const excludedLazyGetters = [];

        for (const fieldName in fields) {
            const field = fields[fieldName];
            if (field.dummy || fieldName === "id") {
                continue;
            }
            // A getter we installed on a previous call is fine to leave in place.
            if (ownGetters.has(fieldName)) {
                continue;
            }
            if (fieldName in ModelRecordClass.prototype) {
                throw new Error(
                    `The property "${fieldName}" defined in the class "${ModelRecordClass.name}" matches an existing model "${modelName}" property. Please use a different property name.`,
                );
            }
            ownGetters.add(fieldName);
            const isRelationNotInModelDef =
                field.relation && !modelNames.has(field.relation);
            if (!RELATION_TYPES.has(field.type) || isRelationNotInModelDef) {
                if (!DATE_TIME_TYPE.has(field.type)) {
                    excludedLazyGetters.push(fieldName);
                }
                Object.defineProperty(ModelRecordClass.prototype, fieldName, {
                    get: function () {
                        const value = this[RAW_SYMBOL][fieldName];
                        if (DATE_TIME_TYPE.has(field.type)) {
                            return field.type === "datetime"
                                ? convertRawToDateTime(this, value, field)
                                : convertRawToDate(this, value, field);
                        } else if (isRelationNotInModelDef && value instanceof Set) {
                            return unmodifiableArray(
                                [...value],
                                `The '${fieldName}' array cannot be modified.`,
                            );
                        }
                        return value;
                    },
                    set: function (newValue) {
                        this.update({ [fieldName]: newValue });
                    },
                    enumerable: true,
                });
            } else {
                const relationModel = field.relation;
                const updateErrorMessage = `The '${fieldName}' array cannot be modified. Use the update method instead.`;
                if (X2MANY_TYPES.has(field.type)) {
                    Object.defineProperty(ModelRecordClass.prototype, fieldName, {
                        get: function () {
                            return unmodifiableArray(
                                Array.from(
                                    this[RAW_SYMBOL][fieldName] || new Set(),
                                    (recordID) =>
                                        this[STORE_SYMBOL].getById(
                                            relationModel,
                                            recordID,
                                        ),
                                ).filter((s) => s), //avoid empty records,
                                updateErrorMessage,
                            );
                        },
                        set: function (values) {
                            this.update({ [fieldName]: values });
                        },
                        enumerable: true,
                    });
                } else if (field.type === "many2one") {
                    Object.defineProperty(ModelRecordClass.prototype, fieldName, {
                        get: function () {
                            const id = this[RAW_SYMBOL][fieldName];
                            if (!id) {
                                return undefined;
                            }
                            return this[STORE_SYMBOL].getById(relationModel, id);
                        },
                        set: function (newValue) {
                            this.update({ [fieldName]: newValue });
                        },
                        enumerable: true,
                    });
                }
            }
        }
        if (excludedLazyGetters.length > 0) {
            ModelRecordClass.excludedLazyGetters = [
                ...ModelRecordClass.excludedLazyGetters,
                ...excludedLazyGetters,
            ];
        }
    }
}
export function createExtraField(record, extraFields, serverData, vals) {
    if (!extraFields?.length) {
        return;
    }
    if (!serverData) {
        // Assign the value to the instance (not in raw data)
        for (let i = 0; i < extraFields.length; i++) {
            const field = extraFields[i];
            record[field] = vals[field];
        }
        return;
    }
    // Create raw data shortcuts getter for the given fields
    for (let i = 0; i < extraFields.length; i++) {
        const fieldName = extraFields[i];
        if (fieldName in record) {
            continue;
        }
        Object.defineProperty(record, fieldName, {
            get: function () {
                const value = this[RAW_SYMBOL][fieldName];
                if (Array.isArray(value)) {
                    return unmodifiableArray(
                        value,
                        `The '${fieldName}' array cannot be modified`,
                    );
                }
                return value;
            },
            set: function (newValue) {
                throw new Error(`${fieldName} is read-only`);
            },
            enumerable: true,
        });
    }
}

function unmodifiableArray(arr, message) {
    return new Proxy(arr, {
        set(target, prop, value) {
            throw new Error(message);
        },
        deleteProperty(target, prop) {
            throw new Error(message);
        },
        defineProperty(target, prop, descriptor) {
            throw new Error(message);
        },
        get(target, prop, receiver) {
            return Reflect.get(target, prop, receiver);
        },
    });
}
