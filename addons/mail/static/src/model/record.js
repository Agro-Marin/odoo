/** @odoo-module native */
import { markup, toRaw } from "@odoo/owl";
import { serializeDate, serializeDateTime } from "@web/core/l10n/dates";

import {
    IS_DELETED_SYM,
    isCommand,
    isMany,
    isOne,
    isRecord,
    isRelation,
    modelRegistry,
    OR_SYM,
} from "./misc.js";

/** @typedef {import("./misc").FieldDefinition} FieldDefinition */
/** @typedef {import("./record_list").RecordList} RecordList */
/**
 * @typedef {Object<string, any>} RecordData
 */
/**
 * @typedef {Object<string, any>} RecordFields
 */
/**
 * @typedef {Object<string, typeof Record>} StoreModels
 */
/**
 * @typedef {Object} Ongoing
 * @property {Object<string, RecordData[]>} storeData
 * @property {Set<string>} seenRecords
 * @property {Set<string>} emittedRecords
 * @property {boolean} depth
 * @property {string[]|undefined} fields
 */
const Markup = markup("").constructor;

/**
 * @param {[string, any][]} command
 * @returns {any}
 */
function idValueOfCommand(command) {
    const [cmd, data] = command.at(-1);
    switch (cmd) {
        case "DELETE":
            return undefined;
        case "DELETE.noinv":
            return [["DELETE.noinv", data]];
        case "ADD.noinv":
            return [["ADD.noinv", data]];
        default:
            return data;
    }
}

export class Record {
    /** @type {import("./model_internal").ModelInternal} */
    static _;
    /** @type {import("./record_internal").RecordInternal} */
    _;
    /** @type {import("./misc").IdExpression} */
    static id;
    /**
     * @type {string|undefined}
     */
    static _name;
    /** @type {import("@web/env").OdooEnv} */
    static env;
    /** @type {import("@web/env").OdooEnv} */
    env;
    /** @type {Object<string, Record>} */
    static records;
    /** @type {import("models").Store} */
    static store;
    /**
     * @type {import("models").Store}
     */
    static _rawStore;
    /**
     * @param {Record} record
     * @param {string|string[]} name
     * @param {() => void} cb
     * @returns {() => void}
     */
    static onChange(record, name, cb) {
        return toRaw(record)._raw._rawStore.onChange(record, name, cb);
    }
    /**
     * @param {Object|string|number} data
     * @returns {Record|undefined}
     */
    static get(data) {
        const Model = toRaw(this);
        return this.records[Model.localId(data)];
    }
    /** @returns {string} */
    static getName() {
        return this._name || this.name;
    }
    /**
     * @param {import("@web/core/registry").Registry<typeof Record>} [localRegistry]
     */
    static register(localRegistry) {
        if (localRegistry) {
            localRegistry.add(this.getName(), this);
        } else {
            modelRegistry.add(this.getName(), this);
        }
    }
    /**
     * @param {Object|string|number} data
     * @returns {string}
     */
    static localId(data) {
        const Model = toRaw(this);
        let idStr;
        if (typeof data === "object" && data !== null) {
            idStr = Model._localId(Model.id, data);
        } else {
            idStr = data;
        }
        return `${Model.getName()},${idStr}`;
    }
    get localId() {
        return toRaw(this)._.localId;
    }
    /**
     * @param {import("./misc").IdExpression} expr
     * @param {RecordData} data
     * @param {Object} [options]
     * @param {boolean} [options.brackets=false]
     * @returns {string|undefined}
     */
    static _localId(expr, data, { brackets = false } = {}) {
        const Model = toRaw(this);
        if (!Array.isArray(expr)) {
            if (Model._.fields.get(expr)) {
                if (isMany(Model, expr)) {
                    throw new Error(
                        "Using a fields.Many() as id is not (yet) supported",
                    );
                }
                if (!isRelation(Model, expr)) {
                    return data[expr];
                }
                if (isCommand(data[expr])) {
                    const [cmd, data2] = data[expr].at(-1);
                    if (cmd === "DELETE") {
                        return undefined;
                    } else {
                        return `(${data2?.localId})`;
                    }
                }
                if (isRecord(data[expr])) {
                    return `(${data[expr]?.localId})`;
                }
                const TargetModelName = Model._.fieldsTargetModel.get(expr);
                const TargetModel = /** @type {StoreModels} */ (
                    /** @type {unknown} */ (Model.store)
                )[TargetModelName];
                return `(${TargetModel.get(data[expr])?.localId})`;
            }
            return data[expr];
        }
        const vals = [];
        for (let i = 1; i < expr.length; i++) {
            vals.push(Model._localId(expr[i], data, { brackets: true }));
        }
        let res = vals.join(expr[0] === OR_SYM ? " OR " : " AND ");
        if (brackets) {
            res = `(${res})`;
        }
        return res;
    }
    /**
     * @param {RecordData|string|number} data
     * @returns {RecordData}
     */
    static _retrieveIdFromData(data) {
        const Model = toRaw(this);
        /** @type {RecordData} */
        const res = {};
        const dataObject = /** @type {RecordData} */ (data);
        /** @param {import("./misc").IdExpression} expr2 */
        function _deepRetrieve(expr2) {
            if (typeof expr2 === "string") {
                res[expr2] = isCommand(dataObject[expr2])
                    ? idValueOfCommand(dataObject[expr2])
                    : dataObject[expr2];
                return;
            }
            if (expr2 instanceof Array) {
                for (const expr of expr2) {
                    if (typeof expr === "symbol") {
                        continue;
                    }
                    _deepRetrieve(expr);
                }
            }
        }
        if (Model.id === undefined) {
            return res;
        }
        if (typeof Model.id === "string") {
            if (typeof data !== "object" || data === null) {
                return { [Model.id]: data };
            }
            _deepRetrieve(Model.id);
            return res;
        }
        for (const expr of Model.id) {
            if (typeof expr === "symbol") {
                continue;
            }
            _deepRetrieve(expr);
        }
        return res;
    }
    /** @type {typeof Record} */
    static Class;
    /**
     * @param {RecordData} data
     * @param {RecordData} ids
     * @returns {Record}
     */
    static new(data, ids) {
        const Model = toRaw(this);
        const store = Model._rawStore;
        return store.MAKE_UPDATE(function RecordNew() {
            const recordProxy = new Model.Class();
            const record = toRaw(recordProxy)._raw;
            Object.assign(record._, { localId: Model.localId(ids) });
            Object.assign(recordProxy, { ...ids });
            Model.records[record.localId] = recordProxy;
            if (record.Model.getName() === "Store") {
                Object.assign(record, {
                    env: Model._rawStore.env,
                    recordByLocalId: Model._rawStore.recordByLocalId,
                });
            }
            Model._rawStore.recordByLocalId.set(record.localId, recordProxy);
            for (const fieldName of record.Model._.fields.keys()) {
                record._.requestCompute?.(record, fieldName);
                record._.requestSort?.(record, fieldName);
            }
            return recordProxy;
        });
    }
    /**
     * @param {RecordData|RecordData[]} data
     * @param {Object} [options]
     * @returns {Record|Record[]}
     */
    static insert(data, options = {}) {
        const ModelFullProxy = this;
        const Model = toRaw(ModelFullProxy);
        const store = Model._rawStore;
        return store.MAKE_UPDATE(function RecordInsert() {
            const isMulti = Array.isArray(data);
            const dataList = isMulti ? data : [data];
            const res = dataList.map(
                /** @param {RecordData} d */
                function RecordInsertMap(d) {
                    return Model._insert.call(ModelFullProxy, d, options);
                },
            );
            if (!isMulti) {
                return res[0];
            }
            return res;
        });
    }
    /**
     * @param {RecordData} data
     * @param {Object} [options]
     * @returns {Record}
     */
    static _insert(data, options) {
        const ModelFullProxy = this;
        const Model = toRaw(ModelFullProxy);
        const recordFullProxy = Model.preinsert.call(ModelFullProxy, data);
        const record = toRaw(recordFullProxy)._raw;
        record.update.call(record._proxy, data);
        return recordFullProxy;
    }
    /**
     * @param {RecordData} data
     * @returns {Record}
     */
    static preinsert(data) {
        const ModelFullProxy = this;
        const Model = toRaw(ModelFullProxy);
        const ids = Model._retrieveIdFromData(data);
        for (const name in ids) {
            if (
                ids[name] &&
                !isRecord(ids[name]) &&
                !isCommand(ids[name]) &&
                isRelation(Model, name)
            ) {
                ids[name] = /** @type {StoreModels} */ (
                    /** @type {unknown} */ (Model._rawStore)
                )[Model._.fieldsTargetModel.get(name)].preinsert(ids[name]);
            }
        }
        return Model.get.call(ModelFullProxy, data) ?? Model.new(data, ids);
    }

    /** @returns {import("models").Store} */
    get store() {
        return toRaw(this)._raw.Model._rawStore._proxy;
    }
    /** @returns {import("models").Store} */
    get _rawStore() {
        return toRaw(this)._raw.Model._rawStore;
    }
    /** @type {typeof Record} */
    Model;
    /** @type {this} */
    _raw;
    /** @type {this} */
    _proxyInternal;
    /** @type {this} */
    _proxy;

    setup() {}

    /** @param {RecordData|string|number} data */
    update(data) {
        const record = toRaw(this)._raw;
        const store = record._rawStore;
        return store.MAKE_UPDATE(function recordUpdate() {
            if (typeof data === "object" && data !== null) {
                store._.updateFields(record, data);
            } else {
                if (Array.isArray(record.Model.id)) {
                    throw new Error(
                        `Cannot insert "${data}" on model "${record.Model.getName()}": this model doesn't support single-id data!`,
                    );
                }
                store._.updateFields(record, { [record.Model.id]: data });
            }
        });
    }

    delete() {
        const record = toRaw(this)._raw;
        const store = record._rawStore;
        return store.MAKE_UPDATE(function recordDelete() {
            store._.ADD_QUEUE("delete", record);
        });
    }

    /** @returns {boolean} */
    exists() {
        return !(/** @type {Object<symbol, boolean>} */ (this)[IS_DELETED_SYM]);
    }

    /**
     * @param {Record} record
     * @returns {boolean}
     */
    eq(record) {
        return toRaw(this)._raw === toRaw(record)?._raw;
    }

    /**
     * @param {Record} record
     * @returns {boolean}
     */
    notEq(record) {
        return !this.eq(record);
    }

    /**
     * @param {Record[]|RecordList} collection
     * @returns {boolean}
     */
    in(collection) {
        if (!collection) {
            return false;
        }
        return collection.some(
            /** @param {Record} record */
            (record) => toRaw(record)._raw.eq(this),
        );
    }

    /**
     * @param {Record[]|RecordList} collection
     * @returns {boolean}
     */
    notIn(collection) {
        return !this.in(collection);
    }

    /**
     * @param {string[] | { depth: boolean }} options
     * @returns {Object<string, RecordData[]>}
     */
    toData(options = { depth: false }) {
        const prefix = this._getActualModelName();
        const isFieldList = Array.isArray(options);
        /** @type {Ongoing} */
        const ongoing = {
            seenRecords: new Set(),
            emittedRecords: new Set(),
            storeData: {},
            depth: isFieldList ? false : options.depth,
            fields: isFieldList
                ? options.map((field) => `${prefix}.${field}`)
                : undefined,
        };
        this._toData(ongoing, prefix);
        return ongoing.storeData;
    }

    /** @param {RecordData} data */
    _cleanupData(data) {
        const fieldsToDelete = [
            "_",
            "_proxy",
            "_proxyInternal",
            "_raw",
            "env",
            "Model",
        ];
        fieldsToDelete.forEach((field) => delete data[field]);
    }

    /** @returns {string} */
    _getActualModelName() {
        return this.Model.getName();
    }

    /**
     * @param {Ongoing} ongoing
     * @param {string} [prefix]
     */
    _toData(ongoing, prefix = undefined) {
        if (ongoing.depth && ongoing.seenRecords.has(this.localId)) {
            return;
        }
        ongoing.seenRecords.add(this.localId);

        const recordProxy = this;
        const record = toRaw(recordProxy)._raw;
        const Model = record.Model;
        /** @type {RecordData} */
        const data = { ...recordProxy };
        const fieldsOfProxy = /** @type {RecordData} */ (recordProxy);
        const fieldsOfInternal = /** @type {RecordData} */ (record._proxyInternal);
        for (const name of Model._.fields.keys()) {
            const fullFieldName = prefix ? `${prefix}.${name}` : name;
            if (isMany(Model, name)) {
                data[name] = fieldsOfInternal[name].map(
                    /** @param {Record} recordProxy */
                    (recordProxy) => {
                        const record = toRaw(recordProxy)._raw;
                        return record._toDataRelationalRecord.call(
                            record._proxyInternal,
                            ongoing,
                            fullFieldName,
                        );
                    },
                );
            } else if (isOne(Model, name)) {
                const otherRecord = toRaw(fieldsOfInternal[name])?._raw;
                data[name] = otherRecord?._toDataRelationalRecord.call(
                    otherRecord._proxyInternal,
                    ongoing,
                    fullFieldName,
                );
            } else {
                const value = fieldsOfProxy[name];
                if (Model._.fieldsType.get(name) === "datetime" && value) {
                    data[name] = serializeDateTime(value);
                } else if (Model._.fieldsType.get(name) === "date" && value) {
                    data[name] = serializeDate(value);
                } else if (Model._.fieldsHtml.get(name) && value instanceof Markup) {
                    data[name] = ["markup", value.toString()];
                } else {
                    data[name] = value;
                }
            }
        }

        this._cleanupData(data);
        if (ongoing.emittedRecords.has(this.localId)) {
            return;
        }
        ongoing.emittedRecords.add(this.localId);
        const pyModelName = record._getActualModelName();
        ongoing.storeData[pyModelName] ||= [];
        ongoing.storeData[pyModelName].push(data);
    }

    /**
     * @param {Ongoing} ongoing
     * @param {string} [prefix]
     * @returns {RecordData}
     */
    _toDataRelationalRecord(ongoing, prefix = undefined) {
        const data = this.Model._retrieveIdFromData(this);
        if (
            ongoing.depth ||
            ongoing.fields?.some(
                (field) => field === prefix || field.startsWith(`${prefix}.`),
            )
        ) {
            this._toData(ongoing, prefix);
        }
        for (const [name, val] of Object.entries(data)) {
            if (isRecord(val)) {
                data[name] = val._toDataRelationalRecord(ongoing, prefix);
            }
        }
        return data;
    }
}
Record.register();
