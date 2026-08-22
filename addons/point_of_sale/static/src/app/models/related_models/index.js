/** @odoo-module native */
import { TrapDisabler } from "@point_of_sale/proxy_trap";
import { uuidv4 } from "@point_of_sale/utils";

import { BackLinkIndex } from "./backlink_index.js";
import { Base } from "./base.js";
import { createExtraField, processModelClasses } from "./model_classes.js";
import { processModelDefs } from "./model_defs.js";
import { RecordStore } from "./record_store.js";
import { ormSerialization } from "./serialization.js";
import {
    AggregatedUpdates,
    BACKREF_PREFIX,
    convertDateTimeToRaw,
    convertDateToRaw,
    DATE_TIME_TYPE,
    mapObj,
    PARENT_X2MANY_TYPES,
    RAW_SYMBOL,
    RELATION_TYPES,
    SERIALIZED_UI_STATE_PROP,
    STORE_SYMBOL,
    X2MANY_TYPES,
} from "./utils.js";

const AVAILABLE_EVENT = ["create", "update", "delete"];

export function createRelatedModels(modelDefs, modelClasses = {}, opts = {}) {
    const database = opts.databaseTable || {};
    const dynamicModels = opts.dynamicModels || [];
    const store = new RecordStore(Object.keys(modelDefs), opts.databaseIndex);
    const [inverseMap, processedModelDefs] = processModelDefs(modelDefs);
    processModelClasses(processedModelDefs, modelClasses);
    const callbacks = mapObj(processedModelDefs, () => []);
    const commands = mapObj(processedModelDefs, () => ({
        delete: new Map(),
        unlink: new Map(),
    }));
    function getFields(model) {
        return processedModelDefs[model];
    }
    const disabler = new TrapDisabler();

    const backlinkIndexes = new Map();

    class Model {
        constructor(name) {
            this.name = name;
            this[STORE_SYMBOL] = store;
            this.records = store.getRecordsMap(this.name);
            this.backlinkVersions = {};
        }

        get models() {
            return models;
        }

        get fields() {
            return getFields(this.name);
        }

        get orderedRecords() {
            return this[STORE_SYMBOL].getOrderedRecords(this.name);
        }

        exists(id) {
            return !!this[STORE_SYMBOL].getById(this.name, id);
        }

        create(vals) {
            return disabler.call((...args) => this._create(...args), vals);
        }

        deserialize(vals) {
            return this.create(vals);
        }

        createMany(valsList) {
            const result = [];
            for (const vals of valsList) {
                result.push(this.create(vals));
            }
            return result;
        }

        update(record, vals, opts = {}) {
            return disabler.call((...args) => this._update(...args), record, vals, {
                ...opts,
            });
        }

        delete(record, opts = {}) {
            return disabler.call((...args) => this._delete(...args), record, opts);
        }

        deleteMany(toDelete, opts = {}) {
            const result = [];
            for (const d of toDelete) {
                result.push(this.delete(d, opts));
            }
            return result;
        }

        read(value) {
            const id = /^\d+$/.test(value) ? parseInt(value) : value;
            return this[STORE_SYMBOL].getById(this.name, id);
        }

        readFirst() {
            return this.orderedRecords[0];
        }

        readBy(key, val) {
            return this[STORE_SYMBOL].get(this.name, key, val);
        }

        readAll() {
            return this.orderedRecords;
        }

        readAllBy(key) {
            return this[STORE_SYMBOL].getRecordsByIds(this.name, key);
        }

        readMany(ids) {
            return ids.map((value) => this.read(value)).filter(Boolean);
        }

        getAllBy() {
            return this.readAllBy(...arguments);
        }

        getAllIds() {
            return this[STORE_SYMBOL].getRecordsIds(this.name);
        }

        getAll() {
            return this.readAll(...arguments);
        }

        getBy() {
            return this.readBy(...arguments);
        }

        get() {
            return this.read(...arguments);
        }

        getFirst() {
            return this.readFirst(...arguments);
        }

        map(fn) {
            return this.orderedRecords.map(fn);
        }

        reduce(fn, initialValue) {
            return this.orderedRecords.reduce(fn, initialValue);
        }

        flatMap(fn) {
            return this.orderedRecords.flatMap(fn);
        }

        forEach(fn) {
            return this.orderedRecords.forEach(fn);
        }

        some(fn) {
            return this.orderedRecords.some(fn);
        }

        every(fn) {
            return this.orderedRecords.every(fn);
        }

        find(fn) {
            return this.orderedRecords.find(fn);
        }

        filter(fn) {
            return this.orderedRecords.filter(fn);
        }

        sort(fn) {
            return this.orderedRecords.sort(fn);
        }

        indexOf(record) {
            return this.orderedRecords.indexOf(record);
        }

        get length() {
            return this[STORE_SYMBOL].getRecordCount(this.name);
        }

        getParentFields() {
            return Object.values(getFields(this.name)).filter((field) => {
                if (field.dummy || !PARENT_X2MANY_TYPES.has(field.type)) {
                    return false;
                }
                const inverseField = inverseMap.get(field);
                return inverseField && !inverseField.dummy;
            });
        }

        addEventListener(event, callback) {
            if (!AVAILABLE_EVENT.includes(event)) {
                throw new Error(`Event '${event}' is not available`);
            }

            if (!(event in callbacks[this.name])) {
                callbacks[this.name][event] = new Map();
            }

            const key = uuidv4();
            callbacks[this.name][event].set(key, callback);
            return () => callbacks[this.name][event].delete(key);
        }

        triggerEvents(event, data) {
            if (
                !(event in callbacks[this.name]) ||
                callbacks[this.name][event].size === 0 ||
                !data
            ) {
                return;
            }

            for (const callback of [...callbacks[this.name][event].values()]) {
                callback(data);
            }
        }

        _sanitizeRawData(vals, options = {}) {
            const {
                connectRecords = true,
                serverData = false,
                existingRecord = false,
            } = options;
            let dataToConnect;
            if (!vals.uuid && database[this.name]?.key === "uuid") {
                vals.uuid = uuidv4();
            }
            vals.id = vals["id"] ?? (vals.uuid || uuidv4());
            const rawData = {
                id: vals.id,
            };
            const fields = getFields(this.name);
            const fieldKeys = Object.keys(fields);
            for (let i = 0; i < fieldKeys.length; i++) {
                const fieldName = fieldKeys[i];
                const field = fields[fieldName];
                const value = vals[fieldName];
                if (field.required && (value === undefined || value === null)) {
                    throw new Error(
                        `'${fieldName}' field is required when creating '${this.name}' record.`,
                    );
                }
                if (existingRecord && !(fieldName in vals)) {
                    rawData[fieldName] = existingRecord[RAW_SYMBOL][fieldName];
                    continue;
                }
                if (RELATION_TYPES.has(field.type)) {
                    if (field.dummy) {
                        continue;
                    }
                    const isX2Many = X2MANY_TYPES.has(field.type);
                    const rawValue = isX2Many ? new Set(value) : value;
                    const data = existingRecord?.[field.name];
                    let localIds = [];
                    if (isX2Many && existingRecord && database[field.relation]?.key) {
                        localIds =
                            data
                                .filter((r) => r.isSynced === false)
                                ?.map((r) => r.id) || [];
                    }

                    if (connectRecords) {
                        if (!dataToConnect) {
                            dataToConnect = {
                                updateFields: {},
                                rawValues: {},
                            };
                        }
                        dataToConnect.updateFields[field.name] = value;
                        if (serverData && !isX2Many) {
                            dataToConnect.rawValues[field.name] = rawValue;
                        } else if (serverData) {
                            dataToConnect.rawValues[field.name] = new Set([
                                ...localIds,
                                ...rawValue,
                            ]);
                        }

                        if (isX2Many) {
                            rawData[field.name] = new Set();
                        } else if (existingRecord) {
                            rawData[field.name] =
                                existingRecord[RAW_SYMBOL][field.name];
                        }
                    } else {
                        if (isX2Many) {
                            rawData[field.name] = new Set([...localIds, ...rawValue]);
                        } else {
                            rawData[field.name] = rawValue;
                        }
                    }
                } else {
                    rawData[fieldName] = DATE_TIME_TYPE.has(field.type)
                        ? field.type === "datetime"
                            ? convertDateTimeToRaw(value)
                            : convertDateToRaw(value)
                        : value;
                }
            }
            const fieldNames = new Set(fieldKeys);
            let uiState;
            let extraFields;
            for (const key in vals) {
                if (fieldNames.has(key)) {
                    continue;
                }
                if (key === SERIALIZED_UI_STATE_PROP) {
                    uiState = JSON.parse(vals[key]);
                } else if (serverData) {
                    rawData[key] = vals[key];
                }

                if (key[0] === "_" && key[1] !== "_") {
                    if (!extraFields) {
                        extraFields = [];
                    }
                    extraFields.push(key);
                }
            }
            return { rawData, uiState, extraFields, dataToConnect };
        }

        _create(vals, opts = {}) {
            const {
                connectRecords = true,
                serverData = false,
                delaySetup = false,
            } = opts;
            const { rawData, uiState, extraFields, dataToConnect } =
                this._sanitizeRawData(vals, {
                    serverData,
                    connectRecords,
                });
            const ModelRecordClass = modelClasses[this.name];
            let record = new ModelRecordClass({
                model: this,
                raw: rawData,
            });
            if (extraFields) {
                createExtraField(record, extraFields, serverData, vals);
            }

            record[STORE_SYMBOL] = this[STORE_SYMBOL];
            record = this[STORE_SYMBOL].add(record);

            if (dataToConnect) {
                this._connectRecords(record, dataToConnect);
            }

            if (!delaySetup) {
                setupRecord(record, vals, uiState);
                record.model.triggerEvents("create", { ids: [record.id] });
                return record;
            }
            return { record, uiState };
        }

        _connectRecords(record, data) {
            this._update(record, data.updateFields, { silent: true });

            if (data.rawValues) {
                Object.assign(record[RAW_SYMBOL], data.rawValues);
            }
        }

        _update(record, vals, opts = {}) {
            const ownFields = getFields(this.name);
            const aggregatedUpdates = new AggregatedUpdates();

            const reIndexRecord = Object.keys(vals).some(
                (name) =>
                    name !== "id" &&
                    !(name === "uuid" && ownFields[name]) &&
                    ownFields[name] &&
                    this[STORE_SYMBOL].hasIndex(this.name, name),
            );
            if (reIndexRecord) {
                this[STORE_SYMBOL].remove(record);
            }

            try {
                for (const name in vals) {
                    if (name === "id" || (name === "uuid" && ownFields[name])) {
                        continue;
                    }

                    const field = ownFields[name];
                    if (!field) {
                        if (opts.omitUnknownField) {
                            continue;
                        }
                        throw new Error(
                            `The field '${name}' does not exist in model '${this.name}'`,
                        );
                    }
                    const coModelName = field.relation;
                    const coModel = this.models[coModelName];
                    if (field.dummy) {
                        throw new Error(`The field '${field.name}' cannot be updated`);
                    }
                    if (coModel) {
                        if (X2MANY_TYPES.has(field.type)) {
                            const commands = convertToX2ManyCommands(
                                vals[name],
                                opts.strict,
                            );
                            for (const cmd of commands) {
                                const [command, ...records] = cmd;
                                if (command === "unlink") {
                                    for (const record2 of records) {
                                        models._disconnect(
                                            field,
                                            record,
                                            record2,
                                            aggregatedUpdates,
                                        );
                                    }
                                } else if (command === "clear") {
                                    const linkedRecs = record[name];
                                    for (const record2 of [...linkedRecs]) {
                                        models._disconnect(
                                            field,
                                            record,
                                            record2,
                                            aggregatedUpdates,
                                        );
                                    }
                                } else if (command === "create") {
                                    const newRecords = records.map((vals) =>
                                        coModel.create(vals),
                                    );
                                    for (const record2 of newRecords) {
                                        models._connect(
                                            field,
                                            record,
                                            record2,
                                            aggregatedUpdates,
                                        );
                                    }
                                } else if (command === "link") {
                                    for (const record2 of records) {
                                        models._connect(
                                            field,
                                            record,
                                            record2,
                                            aggregatedUpdates,
                                        );
                                    }
                                } else if (command === "set") {
                                    const linkedRecs = record[name];
                                    for (const record2 of [...linkedRecs]) {
                                        models._disconnect(
                                            field,
                                            record,
                                            record2,
                                            aggregatedUpdates,
                                        );
                                    }
                                    for (const record2 of records) {
                                        models._connect(
                                            field,
                                            record,
                                            record2,
                                            aggregatedUpdates,
                                        );
                                    }
                                } else {
                                    throw new Error(
                                        "Command '" + command + "' not supported",
                                    );
                                }
                            }
                        } else if (field.type === "many2one") {
                            const value = vals[name];
                            if (value) {
                                const id = value.id || value;
                                const exist = coModel.exists(id);
                                if (exist) {
                                    models._connect(
                                        field,
                                        record,
                                        id,
                                        aggregatedUpdates,
                                    );
                                } else if (
                                    this.models[field.relation] &&
                                    typeof value === "object"
                                ) {
                                    const newRecord = coModel.create(value);
                                    models._connect(
                                        field,
                                        record,
                                        newRecord,
                                        aggregatedUpdates,
                                    );
                                }
                            } else if (record[name]) {
                                models._disconnect(
                                    field,
                                    record,
                                    record[name],
                                    aggregatedUpdates,
                                );
                            }
                        } else {
                            throw new Error(
                                `Relation type '${field.type}' not supported`,
                            );
                        }
                    } else {
                        const oldValue = record[RAW_SYMBOL][name];
                        let newValue = vals[name];
                        if (DATE_TIME_TYPE.has(field.type)) {
                            newValue =
                                field.type === "datetime"
                                    ? convertDateTimeToRaw(newValue)
                                    : convertDateToRaw(newValue);
                        }
                        if (newValue !== oldValue) {
                            record[RAW_SYMBOL][name] = newValue;
                            aggregatedUpdates.add(record, name);
                        }
                    }
                }
            } finally {
                if (reIndexRecord) {
                    this[STORE_SYMBOL].add(record);
                }
            }

            aggregatedUpdates.fireEventAndDirty({
                silentModels: opts.silent ? [record.model.name] : [],
            });
        }

        _delete(record, opts = {}) {
            const id = record.id;
            const ownFields = getFields(this.name);
            const handleCommand = (inverse, field, record, backend = false) => {
                if (inverse && !inverse.dummy && record.isSynced) {
                    const modelCommands = commands[field.relation];
                    const map = backend ? modelCommands.delete : modelCommands.unlink;
                    const oldVal = map.get(inverse.name);
                    map.set(inverse.name, [
                        ...(oldVal || []),
                        { id: record.id, parentId: record[field.name].id },
                    ]);
                }
            };
            this[STORE_SYMBOL].remove(record);
            const aggregatedUpdates = new AggregatedUpdates();
            for (const name in ownFields) {
                const field = ownFields[name];
                const inverse = inverseMap.get(field);
                if (field.dummy) {
                    continue;
                }
                if (X2MANY_TYPES.has(field.type)) {
                    const records = record[name];
                    if (records) {
                        for (const record2 of [...records]) {
                            models._disconnect(
                                field,
                                record,
                                record2,
                                aggregatedUpdates,
                            );
                        }
                    }
                } else if (
                    field.type === "many2one" &&
                    typeof record[name] === "object"
                ) {
                    handleCommand(inverse, field, record, opts.backend);
                    models._disconnect(field, record, record[name], aggregatedUpdates);
                }
            }

            aggregatedUpdates.remove(record);
            aggregatedUpdates.fireEventAndDirty({
                silentModels: opts.silent ? [record.model.name] : [],
            });
            const key = database[this.name]?.key || "id";
            this.triggerEvents("delete", { key: record[key], id: record.id });
            return id;
        }

        backLink(record, link) {
            if (!link.startsWith(BACKREF_PREFIX)) {
                link = BACKREF_PREFIX + link;
            }
            if (link in record) {
                return record[link];
            }
            const field = this.fields[link];
            if (!field) {
                return undefined;
            }
            const backLinkKey = this.name + field.name;
            void this.backlinkVersions[backLinkKey];

            let index = backlinkIndexes.get(backLinkKey);
            if (!index) {
                const bumpVersion = () => {
                    this.backlinkVersions[backLinkKey] =
                        (this.backlinkVersions[backLinkKey] || 0) + 1;
                };
                index = new BackLinkIndex(
                    record[STORE_SYMBOL],
                    field.relation,
                    field.inverse_name,
                    bumpVersion,
                );
                backlinkIndexes.set(backLinkKey, index);

                record.model.addEventListener("delete", (data) =>
                    index.onParentDeleted(data.id),
                );
                const relationModel = record.models[field.relation];
                relationModel.addEventListener("create", (data) =>
                    index.onCreate(data.ids),
                );
                relationModel.addEventListener("update", (data) =>
                    index.onUpdate(data.id, data.fields),
                );
                relationModel.addEventListener("delete", (data) =>
                    index.onDelete(data.id),
                );
            }

            return index.get(record.id);
        }

        serializeForORM(record, opts = {}) {
            return ormSerialization(record, { dynamicModels, ...opts });
        }
        serializeForIndexedDB(record) {
            const serialized = { ...record.raw };
            serialized.__dirty = !!record._dirty;
            const state = record.serializeState();
            if (state) {
                serialized[SERIALIZED_UI_STATE_PROP] = JSON.stringify(state);
            }
            return serialized;
        }
    }

    class Models {
        constructor(processedModelDefs) {
            Object.assign(
                this,
                mapObj(processedModelDefs, (modelName) => new Model(modelName)),
            );
            this[STORE_SYMBOL] = store;
        }

        get commands() {
            return commands;
        }

        /**
         * @param {Object} data
         * @param {Array<string>} [modelsToLoad=[]]
         * @returns {Array<Base>}
         */
        loadConnectedData(data, modelsToLoad = []) {
            return disabler.call(
                (...args) => this._loadData(...args),
                data,
                modelsToLoad,
                {
                    connectRecords: false,
                    serverData: true,
                    preserveLocalDeletions: true,
                },
            );
        }

        /**
         * @param {Object} data
         * @param {boolean} [serverData=true]
         * @returns {Array<Base>}
         */
        connectNewData(data, serverData = true) {
            return disabler.call((...args) => this._loadData(...args), data, [], {
                connectRecords: true,
                serverData: serverData,
            });
        }

        _isPendingDeletion(modelName, key, id) {
            for (const parentModel in commands) {
                const parentFields = getFields(parentModel);
                const modelCommands = commands[parentModel];
                for (const map of [modelCommands.unlink, modelCommands.delete]) {
                    for (const [fieldName, list] of map.entries()) {
                        if (parentFields[fieldName]?.relation !== modelName) {
                            continue;
                        }
                        if (list.some((cmd) => cmd.id === id || cmd.id === key)) {
                            return true;
                        }
                    }
                }
            }
            return false;
        }

        _loadData(rawData, modelsToLoad = [], opts = {}) {
            this._loadingData = true;
            const deferredEvents = [];
            try {
                const results = {};
                const { serverData = true, connectRecords = true } = opts;
                for (const model in rawData) {
                    if (!modelsToLoad.includes(model) && modelsToLoad.length !== 0) {
                        continue;
                    } else if (!results[model]) {
                        results[model] = [];
                    }
                    const modelKey = database[model]?.key || "id";
                    const valsArray = rawData[model] || [];
                    const recordStore = this[STORE_SYMBOL];
                    const modelInstance = this[model];
                    for (const vals of valsArray) {
                        const existingRecord = recordStore.get(
                            model,
                            modelKey,
                            vals[modelKey],
                        );
                        let record,
                            uiState,
                            isUpdate = false;
                        if (
                            opts.preserveLocalDeletions &&
                            !existingRecord &&
                            dynamicModels.includes(model)
                        ) {
                            if (
                                this._isPendingDeletion(model, vals[modelKey], vals.id)
                            ) {
                                continue;
                            }
                        }
                        if (existingRecord) {
                            const {
                                rawData,
                                uiState: newUiState,
                                dataToConnect,
                            } = modelInstance._sanitizeRawData(vals, {
                                connectRecords,
                                serverData,
                                existingRecord,
                            });

                            recordStore.remove(existingRecord);
                            existingRecord[RAW_SYMBOL] = rawData;
                            recordStore.add(existingRecord);
                            if (dataToConnect) {
                                modelInstance._connectRecords(
                                    existingRecord,
                                    dataToConnect,
                                );
                            }
                            record = existingRecord;
                            uiState = newUiState;
                            isUpdate = true;
                        } else {
                            ({ record, uiState } = this[model]._create(vals, {
                                connectRecords,
                                serverData,
                                delaySetup: true,
                            }));
                        }
                        results[model].push({ record, vals, uiState, isUpdate });
                    }
                }
                const finalResults = {};
                for (const model in results) {
                    const entries = results[model];
                    const createdIds = [];
                    const resultsArray = [];
                    finalResults[model] = resultsArray;
                    const modelEvents = this[model];
                    for (let i = 0; i < entries.length; i++) {
                        const { record, vals, uiState, isUpdate } = entries[i];
                        setupRecord(record, vals, uiState, isUpdate);
                        if (!isUpdate) {
                            createdIds.push(record.id);
                        } else {
                            deferredEvents.push([
                                modelEvents,
                                "update",
                                { id: record.id, fields: Object.keys(vals) },
                            ]);
                        }
                        resultsArray.push(record);
                    }
                    if (createdIds.length) {
                        deferredEvents.push([
                            modelEvents,
                            "create",
                            { ids: createdIds },
                        ]);
                    }
                }
                return finalResults;
            } finally {
                this._loadingData = false;
                for (const [target, type, payload] of deferredEvents) {
                    target.triggerEvents(type, payload);
                }
            }
        }

        serializeForORM(record, opts) {
            return ormSerialization(record, { dynamicModels, ...opts });
        }

        _connect(field, ownerRecord, recordOrId, aggregatedUpdates) {
            if (!this[STORE_SYMBOL].hasIndex(field.relation, "id")) {
                return;
            }
            const inverse = inverseMap.get(field);
            const recordToConnect = this._getRecord(field.relation, recordOrId);
            if (!recordToConnect) {
                return;
            }
            if (field.type === "many2one") {
                const prevConnectedRecordId = ownerRecord[RAW_SYMBOL][field.name];
                if (prevConnectedRecordId === recordToConnect.id) {
                    return;
                }
                if (!inverse.dummy && inverse.name in recordToConnect) {
                    this._addItem(
                        recordToConnect,
                        inverse,
                        ownerRecord,
                        aggregatedUpdates,
                    );
                }
                if (prevConnectedRecordId && !inverse.dummy) {
                    const prevRecord = this[STORE_SYMBOL].getById(
                        field.relation,
                        prevConnectedRecordId,
                    );
                    this._removeItem(
                        prevRecord,
                        inverse,
                        ownerRecord,
                        aggregatedUpdates,
                    );
                }
                ownerRecord[RAW_SYMBOL][field.name] = recordToConnect.id;
                aggregatedUpdates.add(ownerRecord, field.name);
            } else if (field.type === "one2many") {
                if (!inverse.dummy) {
                    this._connect(
                        inverse,
                        recordToConnect,
                        ownerRecord,
                        aggregatedUpdates,
                    );
                } else {
                    this._addItem(
                        ownerRecord,
                        field,
                        recordToConnect,
                        aggregatedUpdates,
                    );
                }
            } else if (field.type === "many2many") {
                this._addItem(ownerRecord, field, recordToConnect, aggregatedUpdates);
                this._addItem(recordToConnect, inverse, ownerRecord, aggregatedUpdates);
            }
        }

        _disconnect(field, ownerRecord, recordOrId, aggregatedUpdates) {
            if (!this[STORE_SYMBOL].hasIndex(field.relation, "id")) {
                return;
            }

            const inverse = inverseMap.get(field);
            const recordToDisconnect = this._getRecord(field.relation, recordOrId);
            if (!recordToDisconnect) {
                return;
            }

            if (field.type === "many2one") {
                const prevConnectedRecordId = ownerRecord[RAW_SYMBOL][field.name];
                if (prevConnectedRecordId === recordToDisconnect.id) {
                    ownerRecord[RAW_SYMBOL][field.name] = undefined;
                    aggregatedUpdates.add(ownerRecord, field.name);
                    this._removeItem(
                        recordToDisconnect,
                        inverse,
                        ownerRecord,
                        aggregatedUpdates,
                    );
                }
            } else if (field.type === "one2many") {
                if (!inverse.dummy) {
                    this._disconnect(
                        inverse,
                        recordToDisconnect,
                        ownerRecord,
                        aggregatedUpdates,
                    );
                } else {
                    this._removeItem(
                        ownerRecord,
                        field,
                        recordToDisconnect,
                        aggregatedUpdates,
                    );
                }
            } else if (field.type === "many2many") {
                this._removeItem(
                    ownerRecord,
                    field,
                    recordToDisconnect,
                    aggregatedUpdates,
                );
                this._removeItem(
                    recordToDisconnect,
                    inverse,
                    ownerRecord,
                    aggregatedUpdates,
                );
            }
        }

        _getRecord(model, recordOrId) {
            if (!recordOrId) {
                throw new Error(`Record '${model}' is undefined`);
            }
            if (recordOrId instanceof Base) {
                return recordOrId;
            }
            return this[STORE_SYMBOL].getById(model, recordOrId);
        }

        _removeItem(ownerRecord, field, recordToRemove, aggregatedUpdates) {
            if (field.dummy || !ownerRecord) {
                return;
            }
            if (!recordToRemove.id) {
                return;
            }
            ownerRecord[RAW_SYMBOL][field.name].delete(recordToRemove.id);
            aggregatedUpdates.add(ownerRecord, field.name);
        }

        _addItem(ownerRecord, field, recordToAdd, aggregatedUpdates) {
            if (field.dummy || !ownerRecord) {
                return;
            }
            const recordIds = ownerRecord[RAW_SYMBOL][field.name];
            const idToAdd = recordToAdd.id;
            if (idToAdd && !recordIds.has(idToAdd)) {
                recordIds.add(idToAdd);
                aggregatedUpdates.add(ownerRecord, field.name);
            }
        }
    }

    const models = new Models(processedModelDefs);
    return { models };
}

function setupRecord(record, vals, uiState, isUpdate = false) {
    record.setup(vals);
    if (uiState) {
        record.restoreState(uiState);
    } else if (!isUpdate) {
        record.initState();
    }
}

function convertToX2ManyCommands(values, strict = false) {
    const commands = [];
    let defaultCommand;
    if (!values || values.length === 0) {
        return [["clear"]];
    }
    if (!Array.isArray(values)) {
        throw new Error("The value must be an array");
    }
    for (const val of values) {
        if (Array.isArray(val)) {
            commands.push(val);
        } else {
            if (strict) {
                throw new Error("Only an array of commands is supported");
            }
            if (!defaultCommand) {
                defaultCommand = ["set"];
                commands.push(defaultCommand);
            }
            defaultCommand.push(val);
        }
    }
    return commands;
}

export { Base } from "./base.js";
