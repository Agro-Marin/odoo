/** @odoo-module native */
import { markRaw, reactive, toRaw } from "@odoo/owl";

import {
    ATTR_SYM,
    isFieldDefinition,
    isRelation,
    MANY_SYM,
    modelRegistry,
    STORE_SYM,
} from "./misc.js";
import { ModelInternal } from "./model_internal.js";
import { Record } from "./record.js";
import { RecordInternal } from "./record_internal.js";
import { Store } from "./store.js";
import { StoreInternal } from "./store_internal.js";

/**
 * @param {import("@web/env").OdooEnv} env
 * @returns {{current: import("models").Store}}
 */
function createProvisionalStore(env) {
    const store = new Store();
    store.env = env;
    store.Model = Store;
    store._ = markRaw(new StoreInternal());
    store._raw = store;
    store._proxyInternal = store;
    store._proxy = store;
    store.recordByLocalId = reactive(new Map());
    Record.store = store;
    return { current: store };
}
/**
 * @param {Record} record
 * @param {typeof Record} Model
 * @param {string} name
 * @param {Record} recordFullProxy
 */
function recordProxyGet(record, Model, name, receiver) {
    // `receiver`, not the downgraded proxy: the trap this came from read
    // `arguments`, which in a module is unlinked from the reassigned parameter
    // and so still held the receiver the proxy was invoked with.
    const recordFullProxy = record._.downgradeProxy(record, receiver);
    const kind = Model._.fields.get(name);
    if (record._.gettingField || kind === undefined) {
        let res = Reflect.get(record, name, receiver);
        if (typeof res === "function") {
            res = res.bind(recordFullProxy);
        }
        return res;
    }
    if (kind !== ATTR_SYM) {
        record._.gettingField++;
        let recordList;
        try {
            recordList = recordFullProxy[name];
        } finally {
            record._.gettingField--;
        }
        const recordListFullProxy = recordList._proxy;
        if (kind === MANY_SYM) {
            return recordListFullProxy;
        }
        return recordListFullProxy[0];
    }
    return record[name];
}
/**
 * @param {Record} record
 * @param {typeof Record} Model
 * @param {{current: import("models").Store}} storeRef
 * @param {string} name
 */
function recordProxyDeleteProperty(record, Model, storeRef, name) {
    return storeRef.current.MAKE_UPDATE(function recordDeleteProperty() {
        if (isRelation(Model, name)) {
            const recordList = record[name];
            recordList.clear();
            return true;
        }
        return Reflect.deleteProperty(record, name);
    });
}
/**
 * @param {Record} record
 * @param {{current: import("models").Store}} storeRef
 * @param {string} name
 * @param {any} val
 * @param {Record} receiver
 * @returns {boolean}
 */
function recordProxySet(record, storeRef, name, val, receiver) {
    if (record._.updatingAttrs.has(name)) {
        record[name] = val;
        return true;
    }
    return storeRef.current.MAKE_UPDATE(function recordSet() {
        const reactiveSet = receiver !== record._proxyInternal;
        if (reactiveSet) {
            record._.proxyUsed.set(name, true);
        }
        try {
            storeRef.current._.updateFields(record, {
                [name]: val,
            });
        } finally {
            if (reactiveSet) {
                record._.proxyUsed.delete(name);
            }
        }
        return true;
    });
}
/**
 * @param {Record} record
 * @param {typeof Record} Model
 * @param {{current: import("models").Store}} storeRef
 * @returns {Record}
 */
function makeRecordProxy(record, Model, storeRef) {
    return new Proxy(record, {
        get: (record, name, recordFullProxy) =>
            recordProxyGet(record, Model, name, recordFullProxy),
        deleteProperty: (record, name) =>
            recordProxyDeleteProperty(record, Model, storeRef, name),
        set: (record, name, val, receiver) =>
            recordProxySet(record, storeRef, name, val, receiver),
    });
}
/**
 * @param {typeof Record} OgClass
 * @param {typeof Record} Model
 * @param {{current: import("models").Store}} storeRef
 * @returns {typeof Record}
 */
function makeRecordClass(OgClass, Model, storeRef) {
    return {
        [OgClass.getName()]: class extends OgClass {
            constructor() {
                super();
                this.setup();
                const record = this;
                record._raw = record;
                record.Model = Model;
                record._ = markRaw(
                    record[STORE_SYM] ? new StoreInternal() : new RecordInternal(),
                );
                const recordProxyInternal = makeRecordProxy(record, Model, storeRef);
                record._proxyInternal = recordProxyInternal;
                const recordProxy = reactive(recordProxyInternal);
                record._proxy = recordProxy;
                if (record?.[STORE_SYM]) {
                    record.recordByLocalId = storeRef.current.recordByLocalId;
                    record._ = markRaw(toRaw(storeRef.current._));
                    storeRef.current = record;
                    Record.store = storeRef.current;
                }
                for (const name of Model._.fields.keys()) {
                    record._.prepareField(record, name, recordProxy);
                }
                return recordProxy;
            }
        },
    }[OgClass.getName()];
}
/**
 * @param {typeof Record} Model
 * @param {typeof Record} OgClass
 */
function collectModelFields(Model, OgClass) {
    const obj = new OgClass();
    obj.setup();
    for (const [name, val] of Object.entries(obj)) {
        if (isFieldDefinition(val)) {
            Model._.prepareField(name, val);
        }
    }
    /** @param {import("./misc").IdExpression} expr */
    (function collectIdFields(expr) {
        if (typeof expr === "string") {
            Model._.idFields.add(expr);
        } else if (Array.isArray(expr)) {
            for (const part of expr) {
                if (typeof part !== "symbol") {
                    collectIdFields(part);
                }
            }
        }
    })(Model.id);
}
/** @param {Object<string, typeof Record>} Models */
function linkInverseRelations(Models) {
    for (const Model of Object.values(Models)) {
        for (const name of Model._.fields.keys()) {
            if (!isRelation(Model, name)) {
                continue;
            }
            const targetModel = Model._.fieldsTargetModel.get(name);
            const inverse = Model._.fieldsInverse.get(name);
            if (targetModel && !Models[targetModel]) {
                throw new Error(`No target model ${targetModel} exists`);
            }
            if (inverse) {
                const OtherModel = Models[targetModel];
                if (!isRelation(OtherModel, inverse)) {
                    throw new Error(
                        `Field ${Model.getName()}.${name} declares inverse "${inverse}", but ${OtherModel.getName()} has no fields.One()/fields.Many() named "${inverse}"`,
                    );
                }
                const rel2TargetModel = OtherModel._.fieldsTargetModel.get(inverse);
                const rel2Inverse = OtherModel._.fieldsInverse.get(inverse);
                if (rel2TargetModel && rel2TargetModel !== Model.getName()) {
                    throw new Error(
                        `Fields ${Models[
                            targetModel
                        ].getName()}.${inverse} has wrong targetModel. Expected: "${Model.getName()}" Actual: "${rel2TargetModel}"`,
                    );
                }
                if (rel2Inverse && rel2Inverse !== name) {
                    throw new Error(
                        `Fields ${Models[
                            targetModel
                        ].getName()}.${inverse} has wrong inverse. Expected: "${name}" Actual: "${rel2Inverse}"`,
                    );
                }
                OtherModel._.fieldsTargetModel.set(inverse, Model.getName());
                OtherModel._.fieldsInverse.set(inverse, name);
            }
        }
    }
}
/**
 * @param {Object<string, typeof Record>} Models
 * @param {{current: import("models").Store}} storeRef
 */
function attachStoreToModels(Models, storeRef) {
    for (const Model of Object.values(Models)) {
        Model._rawStore = storeRef.current;
        Model.store = storeRef.current._proxy;
    }
}
/**
 * @param {{current: import("models").Store}} storeRef
 * @param {Object<string, typeof Record>} Models
 */
function bootstrapStoreRecord(storeRef, Models) {
    const temporaryStore = storeRef.current;
    temporaryStore.MAKE_UPDATE(function storeBootstrap() {
        storeRef.current = toRaw(storeRef.current.Store.insert())._raw;
        for (const Model of Object.values(Models)) {
            Model._rawStore = storeRef.current;
            Model.store = storeRef.current._proxy;
            storeRef.current._proxy[Model.getName()] = Model;
        }
        Object.assign(storeRef.current, { Models, storeReady: true });
    });
}
/**
 * @param {import("@web/env").OdooEnv} env
 * @param {Object} [options]
 * @param {import("@web/core/registry").Registry} [options.localRegistry]
 * @returns {import("models").Store}
 */
export function makeStore(env, { localRegistry } = {}) {
    const storeRef = createProvisionalStore(env);
    /** @type {Object<string, typeof Record>} */
    const Models = {};
    const chosenModelRegistry = localRegistry ?? modelRegistry;
    for (const [, _OgClass] of chosenModelRegistry.getEntries()) {
        /** @type {typeof Record} */
        const OgClass = _OgClass;
        if (storeRef.current[OgClass.getName()]) {
            throw new Error(
                `There must be no duplicated Model Names (duplicate found: ${OgClass.getName()})`,
            );
        }
        /** @type {typeof Record} */
        const Model = Object.create(OgClass);
        Model._ = markRaw(new ModelInternal());
        Object.assign(Model, {
            Class: makeRecordClass(OgClass, Model, storeRef),
            records: reactive({}),
        });
        Models[Model.getName()] = Model;
        storeRef.current[Model.getName()] = Model;
        collectModelFields(Model, OgClass);
    }
    linkInverseRelations(Models);
    attachStoreToModels(Models, storeRef);
    bootstrapStoreRecord(storeRef, Models);
    return storeRef.current._proxy;
}
