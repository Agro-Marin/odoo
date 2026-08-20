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
 * @param {Object} [options]
 * @param {import("@web/core/registry").Registry} [options.localRegistry]
 * @returns {import("models").Store}
 */
export function makeStore(env, { localRegistry } = {}) {
    const recordByLocalId = reactive(new Map());
    /** @type {import("models").Store} */
    let store = new Store();
    store.env = env;
    store.Model = Store;
    store._ = markRaw(new StoreInternal());
    store._raw = store;
    store._proxyInternal = store;
    store._proxy = store;
    store.recordByLocalId = recordByLocalId;
    Record.store = store;
    /** @type {Object<string, typeof Record>} */
    const Models = {};
    const chosenModelRegistry = localRegistry ?? modelRegistry;
    for (const [, _OgClass] of chosenModelRegistry.getEntries()) {
        /** @type {typeof Record} */
        const OgClass = _OgClass;
        if (store[OgClass.getName()]) {
            throw new Error(
                `There must be no duplicated Model Names (duplicate found: ${OgClass.getName()})`,
            );
        }
        /** @type {typeof Record} */
        const Model = Object.create(OgClass);
        const Class = {
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
                    const recordProxyInternal = new Proxy(record, {
                        /**
                         * @param {Record} record
                         * @param {string} name
                         * @param {Record} recordFullProxy
                         */
                        get(record, name, recordFullProxy) {
                            recordFullProxy = record._.downgradeProxy(
                                record,
                                recordFullProxy,
                            );
                            const kind = Model._.fields.get(name);
                            if (record._.gettingField || kind === undefined) {
                                let res = Reflect.get(...arguments);
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
                        },
                        /**
                         * @param {Record} record
                         * @param {string} name
                         */
                        deleteProperty(record, name) {
                            return store.MAKE_UPDATE(function recordDeleteProperty() {
                                if (isRelation(Model, name)) {
                                    const recordList = record[name];
                                    recordList.clear();
                                    return true;
                                }
                                return Reflect.deleteProperty(record, name);
                            });
                        },
                        /**
                         * @param {Record} record
                         * @param {string} name
                         * @param {any} val
                         * @param {Record} receiver
                         * @returns {boolean}
                         */
                        set(record, name, val, receiver) {
                            if (record._.updatingAttrs.has(name)) {
                                record[name] = val;
                                return true;
                            }
                            return store.MAKE_UPDATE(function recordSet() {
                                const reactiveSet = receiver !== record._proxyInternal;
                                if (reactiveSet) {
                                    record._.proxyUsed.set(name, true);
                                }
                                try {
                                    store._.updateFields(record, { [name]: val });
                                } finally {
                                    if (reactiveSet) {
                                        record._.proxyUsed.delete(name);
                                    }
                                }
                                return true;
                            });
                        },
                    });
                    record._proxyInternal = recordProxyInternal;
                    const recordProxy = reactive(recordProxyInternal);
                    record._proxy = recordProxy;
                    if (record?.[STORE_SYM]) {
                        record.recordByLocalId = store.recordByLocalId;
                        record._ = markRaw(toRaw(store._));
                        store = record;
                        Record.store = store;
                    }
                    for (const name of Model._.fields.keys()) {
                        record._.prepareField(record, name, recordProxy);
                    }
                    return recordProxy;
                }
            },
        }[OgClass.getName()];
        Model._ = markRaw(new ModelInternal());
        Object.assign(Model, {
            Class,
            records: reactive({}),
        });
        Models[Model.getName()] = Model;
        store[Model.getName()] = Model;
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
    for (const Model of Object.values(Models)) {
        Model._rawStore = store;
        Model.store = store._proxy;
    }
    const temporaryStore = store;
    temporaryStore.MAKE_UPDATE(function storeBootstrap() {
        store = toRaw(store.Store.insert())._raw;
        for (const Model of Object.values(Models)) {
            Model._rawStore = store;
            Model.store = store._proxy;
            store._proxy[Model.getName()] = Model;
        }
        Object.assign(store, { Models, storeReady: true });
    });
    return store._proxy;
}
