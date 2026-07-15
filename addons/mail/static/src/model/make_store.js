/** @odoo-module native */
import { markRaw, reactive, toRaw } from "@odoo/owl";

import {
    isFieldDefinition,
    isMany,
    isRelation,
    modelRegistry,
    STORE_SYM,
} from "./misc.js";
import { ModelInternal } from "./model_internal.js";
import { Record } from "./record.js";
import { RecordInternal } from "./record_internal.js";
import { Store } from "./store.js";
import { StoreInternal } from "./store_internal.js";

/** @returns {import("models").Store} */
export function makeStore(env, { localRegistry } = {}) {
    const recordByLocalId = reactive(new Map());
    // fake store for now, until it becomes a model
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
        // classes cannot be made reactive because they are functions and they are not supported.
        // work-around: make an object whose prototype is the class, so that static props become
        // instance props.
        /** @type {typeof Record} */
        const Model = Object.create(OgClass);
        // Produce another class with changed prototype, so that there are automatic get/set on relational fields
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
                            if (record._.gettingField || !Model._.fields.get(name)) {
                                let res = Reflect.get(...arguments);
                                if (typeof res === "function") {
                                    res = res.bind(recordFullProxy);
                                }
                                return res;
                            }
                            if (isRelation(Model, name)) {
                                // read through the receiver so a reactive
                                // receiver wraps the returned list; the flag
                                // makes the re-entrant trap call fall through.
                                // A counter (not a boolean) so a nested read of
                                // another field on the SAME record doesn't reset
                                // the flag early on its way out.
                                record._.gettingField++;
                                let recordList;
                                try {
                                    recordList = recordFullProxy[name];
                                } finally {
                                    record._.gettingField--;
                                }
                                const recordListFullProxy = recordList._proxy;
                                if (isMany(Model, name)) {
                                    return recordListFullProxy;
                                }
                                return recordListFullProxy[0];
                            }
                            // attrs: single raw read (OWL's own reactive trap
                            // already subscribed the receiver before this ran)
                            return Reflect.get(record, name, recordFullProxy);
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
                         * Using record.update(data) is preferable for performance to batch process
                         * when updating multiple fields at the same time.
                         */
                        set(record, name, val, receiver) {
                            // ensure each field write goes through the updatingAttrs method exactly once
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
                        // Bootstrap: the Store record created by
                        // `store.Store.insert()` in makeStore replaces the
                        // temporary plain store; rebind the makeStore closure
                        // and the `Record.store` global to it. Model refs and
                        // `_rawStore` re-pointing are done by makeStore inside
                        // the same enclosing update cycle, before any flush.
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
        // Detect fields with a dummy record and setup getter/setters on them
        const obj = new OgClass();
        obj.setup();
        for (const [name, val] of Object.entries(obj)) {
            if (isFieldDefinition(val)) {
                Model._.prepareField(name, val);
            }
        }
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
    // Sync inverse fields
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
    /**
     * Point every Model at the temporary plain store so the initial store
     * insert can run: it shares its internal `_` (queues, UPDATE counter)
     * with the real Store record, so both count as one update cycle.
     */
    for (const Model of Object.values(Models)) {
        Model._rawStore = store;
        Model.store = store._proxy;
    }
    /**
     * Bootstrap: create the real store (as a record) inside one enclosing
     * update cycle. Since fields are always eager, the Store record's
     * computes/sorts/hooks (and those of any record they create, e.g. a
     * one-with-compute field like chatHub) are queued during the insert;
     * the enclosing MAKE_UPDATE defers their flush until after every Model
     * has been re-pointed at the real store record and attached to it.
     * Flushing earlier would run computes like `this.Thread.records` or
     * hooks dereferencing `this.store.<field>` against a half-wired store.
     */
    const temporaryStore = store;
    temporaryStore.MAKE_UPDATE(function storeBootstrap() {
        // Make true store (as a model); this reassigns the `store` closure
        // variable to the created record (see the STORE_SYM branch above)
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
