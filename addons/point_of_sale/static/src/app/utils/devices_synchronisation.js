/** @odoo-module native */
import { Domain } from "@web/core/domain";

import { logPosMessage } from "./pretty_console_log.js";
const CONSOLE_COLOR = "#b56be3";
export default class DevicesSynchronisation {
    constructor(dynamicModels, staticModels, posStore) {
        this.setup(dynamicModels, staticModels, posStore);
    }

    /**
     * @param {Array} dynamicModels
     * @param {Array} staticModels
     * @param {Object} posStore
     */
    setup(dynamicModels, staticModels, posStore) {
        this.dynamicModels = new Set(dynamicModels);
        this.staticModels = new Set(staticModels);
        this.pos = posStore;
        this.models = posStore.models;

        this.pos.data.connectWebSocket("SYNCHRONISATION", this.collect.bind(this));
    }

    /**
     * @param {Object} data
     */
    async dispatch(data) {
        const recordIds = Object.entries(data).reduce((acc, [model, records]) => {
            if (!this.staticModels.has(model)) {
                return acc;
            }
            acc[model] = records.map((record) => record.id);
            return acc;
        }, {});

        logPosMessage(
            "Synchronisation",
            "dispatch",
            "Dispatching synchronization",
            CONSOLE_COLOR,
        );
        await this.pos.data.call("pos.config", "notify_synchronisation", [
            odoo.pos_config_id,
            odoo.pos_session_id,
            this.pos.device.identifier,
            recordIds,
        ]);
    }

    /**
     * @param {Object} data
     * @param {String} data.device_identifier
     * @param {Number} data.session_id
     * @param {Object} data.static_records
     */
    async collect(data) {
        const { static_records, session_id, device_identifier } = data;
        const isSameDevice =
            odoo.pos_session_id !== session_id ||
            device_identifier === this.pos.device.identifier;

        logPosMessage(
            "Synchronisation",
            "collect",
            `Incoming synchronization from ${isSameDevice ? "this" : "another"} device`,
            CONSOLE_COLOR,
        );

        if (isSameDevice) {
            return;
        }

        if (Object.keys(static_records).length) {
            this.processStaticRecords(static_records);
        }

        return await this.readDataFromServer();
    }

    async readDataFromServer() {
        const { domain, recordIds } = this.constructOrdersDomain();
        let response;
        try {
            response = await this.pos.data.call(
                "pos.config",
                "read_config_open_orders",
                [odoo.pos_config_id, domain, recordIds],
            );
        } catch (error) {
            logPosMessage(
                "Synchronisation",
                "readDataFromServer",
                `Error reading open orders data from server: ${error}`,
                CONSOLE_COLOR,
            );
            return;
        }

        if (Object.keys(response.dynamic_records).length) {
            const missing = await this.pos.data.missingRecursive(
                response.dynamic_records,
            );
            const { dynamicR, staticR } = Object.entries(missing).reduce(
                (acc, [model, records]) => {
                    if (this.dynamicModels.has(model)) {
                        acc.dynamicR[model] = records;
                    } else if (this.staticModels.has(model)) {
                        acc.staticR[model] = records;
                    }
                    return acc;
                },
                { dynamicR: {}, staticR: {} },
            );

            this.processStaticRecords(staticR);
            const res = await this.processDynamicRecords(dynamicR);
            if (res && res["pos.order"]) {
                const config = this.pos.config;
                const session = this.models["pos.session"].get(odoo.pos_session_id);

                for (const order of res["pos.order"]) {
                    if (!order.isDirty()) {
                        order.serializeForORM();
                    }
                    order.config_id = config;
                    order.session_id = session;
                }
            }
        }

        if (Object.keys(response.deleted_record_ids).length) {
            this.processDeletedRecords(response.deleted_record_ids);
        }
    }

    /**
     * @param {Object} staticRecords
     */
    processStaticRecords(staticRecords) {
        return this.models.connectNewData(staticRecords);
    }

    /**
     * @param {Object} dynamicRecords
     */
    async processDynamicRecords(dynamicRecords) {
        return this.models.connectNewData(dynamicRecords);
    }

    /**
     * @param {Object} deletedRecords
     */
    processDeletedRecords(deletedRecords) {
        for (const [model, ids] of Object.entries(deletedRecords)) {
            const records = this.models[model].readMany(ids).filter(Boolean);
            const dbTable = this.pos.data.opts.databaseTable[model];
            if (dbTable) {
                const key = dbTable.key || "id";
                const keys = records.map((r) => r[key]).filter((k) => k !== undefined);
                if (keys.length) {
                    this.pos.data.deleteRecordsInIndexedDB(model, keys);
                }
            }
            this.models[model].deleteMany(records, { silent: true });
        }
    }

    /**
     * @returns {Array}
     */
    constructOrdersDomain() {
        const databaseTable = this.pos.data.opts.databaseTable;
        const recordsToCheck = Array.from(this.dynamicModels).reduce((acc, model) => {
            const collection = this.models[model];
            if (!collection) {
                return acc;
            }
            acc[model] = collection.filter((r) => !databaseTable[model]?.condition(r));
            return acc;
        }, {});

        const recordIdsByModel = {};
        const domainByModel = {};

        for (const [model, records] of Object.entries(recordsToCheck)) {
            const serverRecs = records.filter((r) => r.isSynced);
            const ids = serverRecs.map((r) => r.id);
            const isOrder = model === "pos.order";

            if (ids.length === 0 && !isOrder) {
                continue;
            }
            recordIdsByModel[model] = ids;

            if (!isOrder) {
                continue;
            }

            const domains = serverRecs.map((record) => {
                const recordDateTimeString = record.write_date
                    .plus({ seconds: 1 })
                    .toUTC()
                    .toFormat("yyyy-MM-dd HH:mm:ss", { numberingSystem: "latn" });
                return Domain.or([
                    new Domain([
                        ["id", "=", record.id],
                        ["write_date", ">=", recordDateTimeString],
                    ]),
                    new Domain([
                        ["id", "=", record.id],
                        ["state", "!=", record.state],
                    ]),
                ]);
            });

            const config = this.pos.config;
            domainByModel[model] = Domain.or([
                Domain.or(domains),
                new Domain([
                    ["id", "not in", ids],
                    ["state", "=", "draft"],
                    ["config_id", "in", [config.id, ...config.raw.trusted_config_ids]],
                ]),
            ]).toList();
        }

        return { domain: domainByModel, recordIds: recordIdsByModel };
    }
}
