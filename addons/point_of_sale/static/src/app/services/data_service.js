/** @odoo-module native */
import { markRaw } from "@odoo/owl";
import { createRelatedModels } from "@point_of_sale/app/models/related_models";
import { getOnNotified, uuidv4 } from "@point_of_sale/utils";
import { browser } from "@web/core/browser/browser";
import { luxon } from "@web/core/l10n/luxon";
import { ConnectionLostError, rpc, RPCError } from "@web/core/network";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { Mutex } from "@web/core/utils/concurrency";
import { SignalStore } from "@web/core/utils/reactive";
import { debounce } from "@web/core/utils/timing";

import { DataServiceOptions } from "../models/data_service_options.js";
import IndexedDB from "../models/utils/indexed_db.js";
import DeviceIdentifierSequence from "../utils/devices_identifier_sequence.js";
import { logPosMessage } from "../utils/pretty_console_log.js";
const { DateTime } = luxon;
const CONSOLE_COLOR = "#28ffeb";
const UNSYNC_QUEUE_STORE = "pos.unsync.queue";
const MAX_SYNC_ATTEMPTS = 5;

export class PosData extends SignalStore {
    static modelToLoad = [];
    static serviceDependencies = ["orm", "bus_service", "dialog"];

    constructor() {
        super();
        this.ready = this.setup(...arguments).then(() => this);
    }

    async setup(env, { orm, bus_service, dialog }) {
        this.dialog = dialog;
        this.orm = orm;
        this.bus = bus_service;
        this.relations = [];
        this.custom = {};
        this.mutex = markRaw(new Mutex());
        this.indexedDBMutex = markRaw(new Mutex());
        this.records = {};
        this.opts = new DataServiceOptions();
        this.channels = [];
        this.debouncedSynchronizeLocalDataInIndexedDB = debounce(
            this.synchronizeLocalDataInIndexedDB.bind(this),
            300,
        );

        this.network = {
            warningTriggered: false,
            offline: false,
            loading: true,
            unsyncData: [],
            deadSyncData: [],
        };

        this.localUnsyncedPaidOrderUuids = new Set();

        await this.checkConnectivity();

        this.initializeWebsocket();
        await this.initializeDeviceIdentifier();
        await this.intializeDataRelation();

        browser.addEventListener("online", () => this.checkConnectivity());
        browser.addEventListener("offline", () => this.checkConnectivity());
        this.bus.addEventListener("BUS:CONNECT", this.reconnectWebSocket.bind(this));
    }

    async initializeDeviceIdentifier() {
        this.device = new DeviceIdentifierSequence({ orm: this.orm });
        await this.device.initialize();
    }

    async checkConnectivity() {
        try {
            clearTimeout(this.checkConnectivityTimeout);
            this.checkConnectivityTimeout = null;
            this.network.offline = false;
            this.network.warningTriggered = false;

            await rpc("/pos/ping");
            await this.syncData();
            window.dispatchEvent(new CustomEvent("pos-network-online"));
        } catch (error) {
            if (error instanceof ConnectionLostError) {
                this.network.offline = true;
                if (navigator.onLine) {
                    this.checkConnectivityTimeout = setTimeout(
                        () => this.checkConnectivity(),
                        2000,
                    );
                }
            }
        }
    }

    initializeWebsocket() {
        this.onNotified = getOnNotified(this.bus, odoo.access_token);
    }

    reconnectWebSocket() {
        this.initializeWebsocket();
        const channels = [...this.channels];
        this.channels = [];
        while (channels.length) {
            const channel = channels.pop();
            this.connectWebSocket(channel.channel, channel.method);

            logPosMessage(
                "DataService",
                "reconnectWebSocket",
                `Reconnecting to channe ${channel.channel}`,
                CONSOLE_COLOR,
            );
        }
    }

    connectWebSocket(channel, method) {
        this.channels.push({
            channel,
            method,
        });

        this.onNotified(channel, method);
    }

    get databaseName() {
        return `point-of-sale-${odoo.pos_config_id}-${odoo.info?.db}`;
    }

    async resetIndexedDB() {
        await this.indexedDB.reset();
    }

    async deleteRecordsInIndexedDB(model, ids) {
        return await this.indexedDB.delete(model, ids);
    }

    async initIndexedDB(relations) {
        const allModelNames = Array.from(
            new Set([
                ...Object.keys(relations),
                ...Object.keys(this.opts.databaseTable),
            ]),
        );
        const models = allModelNames.map((model) => {
            const key = this.opts.databaseTable[model]?.key || "id";
            return [key, model];
        });
        models.push(["uuid", UNSYNC_QUEUE_STORE]);

        return new Promise((resolve) => {
            this.indexedDB = new IndexedDB(
                this.databaseName,
                false,
                models,
                resolve,
                this.dialog,
            );
        });
    }

    async synchronizeLocalDataInIndexedDB() {
        return this.indexedDBMutex.exec(() => this._synchronizeLocalDataInIndexedDB());
    }

    async _synchronizeLocalDataInIndexedDB() {
        const modelsParams = Object.entries(this.opts.databaseTable);
        const data = {};
        for (const [model, params] of modelsParams) {
            const put = [];
            const remove = [];
            const modelData = this.models[model].getAll();

            for (const record of modelData) {
                const isToRemove = params.condition(record);

                if (isToRemove === undefined || isToRemove === true) {
                    if (record[params.key]) {
                        remove.push(record[params.key]);
                    }
                } else {
                    put.push(record.serializeForIndexedDB());
                }
            }

            data[model] = put;

            if (remove.length) {
                await this.indexedDB.delete(model, remove);
            }

            let writeResults;
            if (put.length) {
                writeResults = await this.indexedDB.create(model, put);
            }

            if (model === "pos.order") {
                const writeSucceeded =
                    !put.length ||
                    (Array.isArray(writeResults) &&
                        writeResults.every((r) => r?.status === "fulfilled"));
                const writtenByUuid = new Map(put.map((r) => [r.uuid, r]));
                for (const trackedUuid of [...this.localUnsyncedPaidOrderUuids]) {
                    const written = writtenByUuid.get(trackedUuid);
                    const localRecord = this.models[model].getBy("uuid", trackedUuid);
                    if (!localRecord?.isUnsyncedPaid) {
                        this.localUnsyncedPaidOrderUuids.delete(trackedUuid);
                    } else if (written?.state === "paid" && writeSucceeded) {
                        this.localUnsyncedPaidOrderUuids.delete(trackedUuid);
                    } else {
                        logPosMessage(
                            "DataService",
                            "synchronizeLocalDataInIndexedDB",
                            `Paid order ${trackedUuid} is flagged unsynced but not confirmed durable (written=${!!written}, writeOk=${writeSucceeded}) — keeping data-loss guard`,
                            CONSOLE_COLOR,
                        );
                    }
                }
            }
        }

        return data;
    }

    async synchronizeServerDataInIndexedDB(serverData = {}) {
        try {
            const clone = JSON.parse(JSON.stringify(serverData));
            for (const [model, data] of Object.entries(clone)) {
                try {
                    await this.indexedDB.create(model, data);
                } catch {
                    logPosMessage(
                        "DataService",
                        "synchronizeServerDataInIndexedDB",
                        `Error while updating ${model} in indexedDB.`,
                        CONSOLE_COLOR,
                    );
                }
            }
        } catch {
            logPosMessage(
                "DataService",
                "synchronizeServerDataInIndexedDB",
                "Error while synchronizing server data in indexedDB.",
                CONSOLE_COLOR,
            );
        }
    }

    async getLocalDataFromIndexedDB(data = false) {
        const models = Object.keys(this.opts.databaseTable);

        if (!data) {
            data = await this.indexedDB.readAll(models);
        }

        if (!data) {
            return;
        }

        const preLoadData = await this.preLoadData(data);
        const missing = await this.missingRecursive(preLoadData);

        const serverProductIds = this.models["product.product"].map((p) => p.id);
        const databaseProductIds = missing["product.product"]?.map((p) => p.id) ?? [];
        const loadedProductIds = new Set([...databaseProductIds, ...serverProductIds]);
        const restoredLines = missing["pos.order.line"] ?? [];
        missing["pos.order.line"] = restoredLines.filter((line) =>
            loadedProductIds.has(line.product_id),
        );
        const droppedLines = restoredLines.length - missing["pos.order.line"].length;
        if (droppedLines) {
            logPosMessage(
                "DataService",
                "getLocalDataFromIndexedDB",
                `Dropped ${droppedLines} restored order line(s) whose product is not loaded; the owning orders will show an incomplete total`,
                CONSOLE_COLOR,
            );
        }

        const results = this.models.loadConnectedData(missing, []);

        await this.checkAndDeleteMissingOrders(results);

        return results;
    }

    async getCachedServerDataFromIndexedDB() {
        const data = await this.indexedDB.readAll();
        const modelToIgnore = new Set(Object.keys(this.opts.databaseTable));
        const results = {};

        for (const name in data) {
            if (modelToIgnore.has(name)) {
                continue;
            }
            results[name] = data[name];
        }

        return results;
    }

    async loadInitialData() {
        let localData = await this.getCachedServerDataFromIndexedDB();
        const session = localData?.["pos.session"]?.[0];

        if (
            (!this.network.offline && session?.state !== "opened") ||
            session?.id !== odoo.pos_session_id ||
            odoo.from_backend
        ) {
            try {
                const limitedLoading = this.isLimitedLoading();
                const serverDate = localData["pos.config"]?.[0]?._data_server_date;
                const lastConfigChange = DateTime.fromSQL(odoo.last_data_change);
                const serverDateTime = DateTime.fromSQL(serverDate);

                if (serverDateTime < lastConfigChange) {
                    await this.resetIndexedDB();
                    await this.initIndexedDB(this.relations);
                    localData = {};
                }

                const data = await this.orm.call(
                    "pos.session",
                    "load_data",
                    [odoo.pos_session_id, PosData.modelToLoad],
                    {
                        context: {
                            pos_last_server_date:
                                serverDateTime > lastConfigChange && serverDate,
                            pos_limited_loading: limitedLoading,
                        },
                    },
                );

                const local_records_to_filter = {};
                for (const model of this.opts.cleanupModels) {
                    const local = localData[model] || [];
                    if (local.length > 0) {
                        local_records_to_filter[model] = local.map((r) => r.id);
                    }
                }

                const data_to_remove = await this.orm.call(
                    "pos.session",
                    "filter_local_data",
                    [odoo.pos_session_id, local_records_to_filter],
                );

                for (const [model, values] of Object.entries(data)) {
                    let local = localData[model] || [];

                    if (this.opts.uniqueModels.includes(model) && values.length > 0) {
                        this.indexedDB.delete(
                            model,
                            local.map((r) => r.id),
                        );
                        localData[model] = values;
                    } else {
                        if (data_to_remove[model] && data_to_remove[model].length > 0) {
                            const remove_ids = data_to_remove[model];
                            local = local.filter((r) => !remove_ids.includes(r.id));
                            this.indexedDB.delete(model, remove_ids);
                        }
                        localData[model] = local.concat(values);
                    }
                }

                this.synchronizeServerDataInIndexedDB(localData);
            } catch (error) {
                let message = _t(
                    "An error occurred while loading the Point of Sale: \n",
                );
                if (error instanceof RPCError) {
                    message += error.data.message;
                } else {
                    message += error.message;
                }
                window.alert(message);
                return localData;
            }
        }

        return localData;
    }

    async initData() {
        const data = await this.loadInitialData();
        const order = data["pos.order"] || [];
        const orderlines = data["pos.order.line"] || [];

        delete data["pos.order"];
        delete data["pos.order.line"];

        this.models.loadConnectedData(data, this.modelToLoad);
        this.models.loadConnectedData(
            { "pos.order": order, "pos.order.line": orderlines },
            [],
        );
        this.sanitizeData();
    }

    async sanitizeData() {
        const order_to_delete = this.models["pos.order"].filter((order) =>
            order.lines.some(
                (line) => line.is_reward_line && !line.coupon_id && !line.reward_id,
            ),
        );
        for (const order of order_to_delete) {
            for (let i = order.lines.length - 1; i >= 0; i--) {
                order.lines[i].delete();
            }
        }
    }

    async loadFieldsAndRelations() {
        const key = `pos_data_params_${odoo.pos_config_id}`;
        if (this.network.offline) {
            return JSON.parse(localStorage.getItem(key));
        }

        try {
            const params = await this.orm.call("pos.session", "load_data_params", [
                odoo.pos_session_id,
            ]);
            localStorage.setItem(key, JSON.stringify(params));
            return params;
        } catch {
            return JSON.parse(localStorage.getItem(key));
        }
    }

    async intializeDataRelation() {
        const modelClasses = {};
        const fields = {};
        const relations = {};
        const dataParams = await this.loadFieldsAndRelations();
        await this.initIndexedDB(dataParams);
        await this.restoreUnsyncQueue();

        for (const [model, values] of Object.entries(dataParams)) {
            relations[model] = values.relations;
            fields[model] = values.fields;
        }

        for (const posModel of registry.category("pos_available_models").getAll()) {
            const pythonModel = posModel.pythonModel;
            const extraFields = posModel.extraFields || {};

            modelClasses[pythonModel] = posModel;
            relations[pythonModel] = {
                ...relations[pythonModel],
                ...extraFields,
            };
        }

        const { models } = createRelatedModels(relations, modelClasses, this.opts);

        this.fields = fields;
        this.relations = relations;
        this.models = models;

        if (odoo.debug === "assets") {
            window.performance.mark("pos_data_service_init");
        }

        await this.initData();
        await this.getLocalDataFromIndexedDB();
        this.initListeners();
        this.drainRestoredQueue();

        if (odoo.debug === "assets") {
            window.performance.mark("pos_data_service_init_end");
            this.debugInfos();
        }

        this.network.loading = false;
    }

    debugInfos() {
        const measure = window.performance.measure(
            "pos_loading",
            "pos_data_service_init",
            "pos_data_service_init_end",
        );

        logPosMessage(
            "DataService",
            "debugInfos",
            `PosDataService initialized in ${measure.duration.toFixed(2)}ms`,
            CONSOLE_COLOR,
        );
    }

    initListeners() {
        const databaseTable = this.opts.databaseTable;
        for (const dynamicModel of this.opts.dynamicModels) {
            if (!this.models[dynamicModel]) {
                continue;
            }

            this.models[dynamicModel].addEventListener(
                "update",
                this.debouncedSynchronizeLocalDataInIndexedDB.bind(this),
            );

            if (databaseTable[dynamicModel]) {
                this.models[dynamicModel].addEventListener("delete", (params) => {
                    if (params.key !== undefined) {
                        this.indexedDB.delete(dynamicModel, [params.key]);
                    }
                });
            }
        }

        const ignore = new Set(Object.keys(this.opts.databaseTable));
        for (const model of Object.keys(this.relations)) {
            if (ignore.has(model)) {
                continue;
            }

            this.models[model].addEventListener("delete", (params) => {
                this.indexedDB.delete(model, [params.key]);
            });

            this.models[model].addEventListener("update", (params) => {
                const record = this.models[model].get(params.id)?.raw;
                if (!record) {
                    return;
                }
                this.synchronizeServerDataInIndexedDB({ [model]: [record] });
            });
        }
    }

    async execute({
        type,
        model,
        ids,
        values,
        method,
        queue,
        args = [],
        kwargs = {},
        fields = [],
        options = [],
        uuid = "",
    }) {
        this._inFlight = (this._inFlight ?? 0) + 1;
        this.network.loading = true;

        try {
            if (this.network.offline) {
                throw new ConnectionLostError();
            }

            let result = true;
            let limitedFields = false;
            if (fields.length === 0) {
                fields = this.fields[model] || [];
            }

            const modelFields = this.fields[model];
            if (
                modelFields &&
                [...fields].sort().join(",") !== [...modelFields].sort().join(",")
            ) {
                limitedFields = true;
            }

            switch (type) {
                case "write":
                    result = await this.orm.write(model, ids, values);
                    break;
                case "delete":
                    result = await this.orm.unlink(model, ids);
                    break;
                case "call":
                    result = await this.orm.call(model, method, args, kwargs);
                    break;
                case "read":
                    queue = false;
                    result = await this.orm.read(model, ids, fields, {
                        ...options,
                        load: false,
                    });
                    break;
                case "search_read":
                    queue = false;
                    result = await this.orm.searchRead(model, args, fields, {
                        ...options,
                        load: false,
                    });
            }

            if (type === "create") {
                const response = await this.orm.create(model, values);
                values[0].id = response[0];
                result = values;
            }

            const nonExistentRecords = [];
            if (limitedFields) {
                const X2MANY_TYPES = new Set(["many2many", "one2many"]);

                for (const record of result) {
                    const localRecord = this.models[model].get(record.id);

                    if (localRecord) {
                        const formattedForUpdate = {};
                        for (const [field, value] of Object.entries(record)) {
                            const fieldsParams = this.relations[model][field];

                            if (!fieldsParams) {
                                logPosMessage(
                                    "DataService",
                                    "execute",
                                    "Warning, attempt to load a non-existent field.",
                                    CONSOLE_COLOR,
                                );
                                continue;
                            }

                            if (X2MANY_TYPES.has(fieldsParams.type)) {
                                formattedForUpdate[field] = value
                                    .filter((id) =>
                                        this.models[fieldsParams.relation].get(id),
                                    )
                                    .map((id) => [
                                        "link",
                                        this.models[fieldsParams.relation].get(id),
                                    ]);
                            } else if (fieldsParams.type === "many2one") {
                                if (this.models[fieldsParams.relation].get(value)) {
                                    formattedForUpdate[field] = [
                                        "link",
                                        this.models[fieldsParams.relation].get(value),
                                    ];
                                }
                            } else {
                                formattedForUpdate[field] = value;
                            }
                        }

                        localRecord.update(formattedForUpdate, {
                            omitUnknownField: true,
                        });
                        this.synchronizeServerDataInIndexedDB({
                            [model]: [localRecord.raw],
                        });
                    } else {
                        nonExistentRecords.push(record);
                    }
                }

                if (nonExistentRecords.length) {
                    logPosMessage(
                        "DataService",
                        "execute",
                        "Warning, attempt to load a non-existent record with limited fields.",
                        CONSOLE_COLOR,
                    );
                    result = nonExistentRecords;
                }
            }

            if (
                this.models[model] &&
                this.opts.autoLoadedOrmMethods.includes(type) &&
                (!limitedFields || nonExistentRecords.length)
            ) {
                const data = await this.missingRecursive({ [model]: result });
                this.synchronizeServerDataInIndexedDB(data);
                const results = this.models.connectNewData(data);
                result = results[model];
            } else if (type === "write") {
                const localRecord = this.models[model].get(ids[0]);
                if (localRecord) {
                    localRecord.update(values, { omitUnknownField: true });
                    this.synchronizeServerDataInIndexedDB({
                        [model]: [localRecord.raw],
                    });
                }
            }

            if (result === null || result === undefined) {
                return true;
            }
            return result;
        } catch (error) {
            let throwErr = true;
            const uuids = this.network.unsyncData.map((d) => d.uuid);
            if (
                queue &&
                !uuids.includes(uuid) &&
                method !== "sync_from_ui" &&
                error instanceof ConnectionLostError
            ) {
                const entry = {
                    args: [...arguments],
                    date: DateTime.now(),
                    try: 1,
                    uuid: uuidv4(),
                };
                this.network.unsyncData.push(entry);
                this._persistQueueEntry(entry);

                throwErr = false;
            }

            if (throwErr) {
                throw error;
            }
        } finally {
            this._inFlight -= 1;
            this.network.loading = this._inFlight > 0;
        }
    }

    async missingRecursive(recordMap, idsMap = {}, acc = {}) {
        for (const [model, records] of Object.entries(recordMap)) {
            if (!acc[model]) {
                acc[model] = records;
            } else {
                acc[model] = acc[model].concat(records);
            }
        }

        if (this.network.offline) {
            return acc;
        }

        const missingRecords = {};
        const recordInMapByModelIds = Object.entries(recordMap).reduce(
            (acc, [model, records]) => {
                acc[model] = new Set(records.map((r) => r.id));
                return acc;
            },
            {},
        );

        for (const [model, records] of Object.entries(recordMap)) {
            if (!this.relations[model]) {
                continue;
            }

            const relations = Object.entries(this.relations[model]).filter(
                ([, rel]) => rel.relation && rel.type && this.models[rel.relation],
            );

            for (const [, rel] of relations) {
                if (this.opts.prohibitedAutoLoadedModels.includes(rel.relation)) {
                    continue;
                }

                if (
                    this.opts.prohibitedAutoLoadedFields[rel.model]?.includes(rel.name)
                ) {
                    continue;
                }

                const values = records.map((record) => record[rel.name]).flat();
                const missing = values.filter((value) => {
                    if (
                        !value ||
                        typeof value !== "number" ||
                        idsMap[rel.relation]?.has(value)
                    ) {
                        return false;
                    }

                    const record = this.models[rel.relation].get(value);
                    return (
                        (!record || !record.id) &&
                        !recordInMapByModelIds[rel.relation]?.has(value)
                    );
                });

                if (missing.length > 0) {
                    if (!missingRecords[rel.relation]) {
                        missingRecords[rel.relation] = new Set(missing);
                    } else {
                        missingRecords[rel.relation] = new Set([
                            ...missingRecords[rel.relation],
                            ...missing,
                        ]);
                    }
                }
            }
        }

        const newRecordMap = {};
        for (const [model, ids] of Object.entries(missingRecords)) {
            if (!idsMap[model]) {
                idsMap[model] = new Set(ids);
            } else {
                idsMap[model] = idsMap[model] = new Set([...idsMap[model], ...ids]);
            }

            try {
                if (["product.product", "product.template"].includes(model)) {
                    const domain =
                        model === "product.product" ? "product_variant_ids.id" : "id";
                    await this.callRelated(
                        "product.template",
                        "load_product_from_pos",
                        [odoo.pos_config_id, [[domain, "in", Array.from(ids)]], 0, 0],
                        {
                            context: {
                                load_archived: true,
                            },
                        },
                    );
                    continue;
                }

                const data = await this.orm.read(
                    model,
                    Array.from(ids),
                    this.fields[model],
                    {
                        load: false,
                    },
                );
                newRecordMap[model] = data;
            } catch {
                newRecordMap[model] = [];
            }
        }

        if (Object.keys(newRecordMap).length > 0) {
            return await this.missingRecursive(newRecordMap, idsMap, acc);
        } else {
            return acc;
        }
    }

    _persistQueueEntry(entry) {
        this.indexedDB
            ?.create(UNSYNC_QUEUE_STORE, [
                {
                    uuid: entry.uuid,
                    date: entry.date?.toISO?.() ?? String(entry.date ?? ""),
                    try: entry.try ?? 1,
                    args: entry.args,
                },
            ])
            ?.catch?.(() => {});
    }

    _unpersistQueueEntry(uuid) {
        this.indexedDB?.delete(UNSYNC_QUEUE_STORE, [uuid])?.catch?.(() => {});
    }

    async restoreUnsyncQueue() {
        try {
            const data = await this.indexedDB.readAll([UNSYNC_QUEUE_STORE]);
            const rows = data?.[UNSYNC_QUEUE_STORE] || [];
            for (const row of rows) {
                if (!this.network.unsyncData.some((d) => d.uuid === row.uuid)) {
                    this.network.unsyncData.push({
                        args: row.args,
                        date: row.date,
                        try: row.try ?? 1,
                        uuid: row.uuid,
                    });
                }
            }
        } catch {
            logPosMessage(
                "DataService",
                "restoreUnsyncQueue",
                "Could not restore the offline retry queue from IndexedDB",
                CONSOLE_COLOR,
            );
        }
    }

    drainRestoredQueue() {
        if (!this.network.unsyncData.length || this.network.offline) {
            return;
        }
        this.syncData().catch((error) => {
            logPosMessage(
                "DataService",
                "drainRestoredQueue",
                "Could not replay the restored offline queue; entries stay queued",
                CONSOLE_COLOR,
                [error],
            );
        });
    }

    async syncData() {
        await this.mutex.exec(async () => {
            while (this.network.unsyncData.length > 0) {
                const data = this.network.unsyncData[0];
                try {
                    await this.execute({ ...data.args[0], uuid: data.uuid });
                    this.network.unsyncData.shift();
                    this._unpersistQueueEntry(data.uuid);
                    const params = data.args[0];
                    if (params?.type === "write" && this.deviceSync?.dispatch) {
                        Promise.resolve(
                            this.deviceSync.dispatch({
                                [params.model]: params.ids.map((id) => ({ id })),
                            }),
                        ).catch(() => {});
                    }
                } catch (error) {
                    if (error instanceof ConnectionLostError) {
                        throw error;
                    }
                    if (!(error instanceof RPCError)) {
                        data.try = (data.try ?? 1) + 1;
                        if (data.try <= MAX_SYNC_ATTEMPTS) {
                            this._persistQueueEntry(data);
                            throw error;
                        }
                        logPosMessage(
                            "DataService",
                            "syncData",
                            `A queued offline operation failed ${MAX_SYNC_ATTEMPTS} times client-side and will not be retried`,
                            CONSOLE_COLOR,
                            [error, data],
                        );
                    }
                    this.network.unsyncData.shift();
                    this._unpersistQueueEntry(data.uuid);
                    this.network.deadSyncData.push({ ...data, error });
                    logPosMessage(
                        "DataService",
                        "syncData",
                        "A queued offline operation was rejected by the server and will not be retried",
                        CONSOLE_COLOR,
                        [error, data],
                    );
                }
            }
        });
    }

    async loadServerOrders(domain) {
        const result = await this.callRelated(
            "pos.order",
            "read_pos_orders",
            [domain],
            {},
            false,
            true,
        );
        const config = this.models["pos.config"].get(odoo.pos_config_id);
        const session = this.models["pos.session"].get(odoo.pos_session_id);
        const orders = result["pos.order"] || [];
        for (const order of orders) {
            if (!order.isDirty()) {
                order.serializeForORM();
            }
            order.config_id = config;
            order.session_id = session;
        }
        return orders;
    }

    async checkAndDeleteMissingOrders(results) {
        if (results && results["pos.order"]) {
            const ids = new Set(
                results["pos.order"].filter((o) => o.isSynced).map((o) => o.id),
            );
            if (ids.size) {
                const orders = await this.loadServerOrders([["id", "in", [...ids]]]);
                const serverIds = orders.map((r) => r.id);
                for (const id of [...ids]) {
                    if (!serverIds.includes(id)) {
                        this.localDeleteCascade(this.models["pos.order"].get(id));
                    }
                }
            }
        }
    }

    async write(model, ids, vals) {
        const records = [];

        for (const id of ids) {
            const record = this.models[model].get(id);
            if (!record) {
                continue;
            }
            delete vals.id;

            const keysToUpdate = Object.keys(vals);
            const previous = {};
            for (const key of keysToUpdate) {
                const value = record[key];
                previous[key] = Array.isArray(value) ? [...value] : value;
            }
            record.update(vals, { omitUnknownField: true });

            const dataToUpdate = {};
            for (const key of keysToUpdate) {
                dataToUpdate[key] = vals[key];
            }

            records.push(record);
            if (typeof id === "number") {
                try {
                    await this.ormWrite(model, [record.id], dataToUpdate);
                } catch (error) {
                    record.update(previous, { omitUnknownField: true });
                    throw error;
                }
            }
        }

        return records;
    }

    delete(model, ids) {
        const deleted = [];
        for (const id of ids) {
            const record = this.models[model].get(id);
            if (!record) {
                continue;
            }
            deleted.push(id);
            record.delete();
        }

        Promise.resolve(this.ormDelete(model, ids)).catch((error) => {
            logPosMessage(
                "DataService",
                "delete",
                `Could not delete ${model} ${ids} on the server`,
                CONSOLE_COLOR,
                [error],
            );
        });
        return deleted;
    }

    async searchRead(model, domain = [], fields = [], options = {}, queue = false) {
        return await this.execute({
            type: "search_read",
            model,
            args: domain,
            fields,
            options,
            queue,
        });
    }

    async read(model, ids, fields = [], options = [], queue = false) {
        return await this.execute({
            type: "read",
            model,
            ids,
            fields,
            options,
            queue,
        });
    }

    async call(model, method, args = [], kwargs = {}, queue = false) {
        return await this.execute({
            type: "call",
            model,
            method,
            args,
            kwargs,
            queue,
        });
    }

    async silentCall(model, method, args = [], kwargs = {}, queue = false) {
        try {
            return await this.execute({
                type: "call",
                model,
                method,
                args,
                kwargs,
                queue,
            });
        } catch (e) {
            logPosMessage(
                "DataService",
                "silentCall",
                "Silent call failed",
                CONSOLE_COLOR,
                [e],
            );
            return false;
        }
    }

    async callRelated(
        model,
        method,
        args = [],
        kwargs = {},
        queue = true,
        loadMessingRecords = false,
    ) {
        let data = await this.execute({
            type: "call",
            model,
            method,
            args,
            kwargs,
            queue,
        });

        if (loadMessingRecords) {
            data = await this.missingRecursive(data);
        }

        if (data) {
            this.deviceSync?.dispatch && this.deviceSync.dispatch(data);
            const result = this.models.connectNewData(data);
            this.synchronizeServerDataInIndexedDB(data);
            return result;
        }
        return false;
    }

    async create(model, values, queue = true) {
        return await this.execute({ type: "create", model, values, queue });
    }

    async ormWrite(model, ids, values, queue = true) {
        const result = await this.execute({
            type: "write",
            model,
            ids,
            values,
            queue,
        });
        if (result !== undefined && this.deviceSync?.dispatch) {
            Promise.resolve(
                this.deviceSync.dispatch({ [model]: ids.map((id) => ({ id })) }),
            ).catch(() => {});
        }
        return result;
    }

    async ormDelete(model, ids, queue = true) {
        return await this.execute({ type: "delete", model, ids, queue });
    }

    localDeleteCascade(record, removeFromServer = false) {
        const recordModel = record.model.name;

        const cascadeDeleteModels = new Set(this.opts.cascadeDeleteModels);
        const databaseTable = this.opts.databaseTable;

        const relationsToDelete = Object.values(this.relations[recordModel])
            .filter((rel) => cascadeDeleteModels.has(rel.relation))
            .map((rel) => rel.name);
        const recordsToDelete = relationsToDelete.flatMap(
            (relation) => record[relation] || [],
        );

        const idbKey = (rec) => rec[databaseTable[rec.model.name]?.key || "id"];
        this.deleteRecordsInIndexedDB(recordModel, [idbKey(record)]);
        for (const item of recordsToDelete) {
            this.deleteRecordsInIndexedDB(item.model.name, [idbKey(item)]);
            item.delete({ silent: !removeFromServer });
        }

        const result = record.delete({ silent: !removeFromServer });
        return result;
    }

    async preLoadData(data) {
        return data;
    }

    isLimitedLoading() {
        const url = new URL(window.location.href);
        const limitedLoading =
            url.searchParams.get("limited_loading") === "0" ? false : true;

        if (!limitedLoading) {
            url.searchParams.delete("limited_loading");
            window.history.replaceState({}, "", url);
        }

        return limitedLoading;
    }
}

export const PosDataService = {
    dependencies: PosData.serviceDependencies,
    async start(env, deps) {
        return new PosData(env, deps).ready;
    },
};

registry.category("services").add("pos_data", PosDataService);
