/** @odoo-module native */
import { Domain } from "@web/core/domain";

import { logPosMessage } from "./pretty_console_log.js";
const CONSOLE_COLOR = "#b56be3";
/**
 * Class representing the synchronization of records.
 * This class handles the setup and management of dynamic (flexible) models
 * that can be created in the frontend and static models that are predefined.
 */
export default class DevicesSynchronisation {
    constructor(dynamicModels, staticModels, posStore) {
        this.setup(dynamicModels, staticModels, posStore);
    }

    /**
     * Setup the record synchronization with dynamic and static models.
     * @param {Array} dynamicModels - Models that can be created in the frontend.
     * @param {Array} staticModels - Predefined models that are static.
     * @param {Object} posStore - The posStore instance.
     */
    setup(dynamicModels, staticModels, posStore) {
        this.dynamicModels = new Set(dynamicModels);
        this.staticModels = new Set(staticModels);
        this.pos = posStore;
        this.models = posStore.models;

        // Connect websocket to receive synchronisation notification
        this.pos.data.connectWebSocket("SYNCHRONISATION", this.collect.bind(this));
    }

    /**
     * Notify the backend that records changed, so other devices can sync.
     * @param {Object} data - The changed records, keyed by model.
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
     * Handle an incoming sync notification and refresh local records.
     * @param {Object} data - The data that needs to be synchronized.
     * @param {String} data.device_identifier - Session login number.
     * @param {Number} data.session_id - Current session id.
     * @param {Object} data.static_records - Records data that need to be synchronized.
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

    /**
     * Read updated open-order data from the server and apply it locally.
     */
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
                    // Consume stale commands — but never for a locally-dirty
                    // order: its pending unlink/delete commands are exactly
                    // the edits the next sync must still send.
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
     * Apply synchronized static records to the frontend.
     * @param {Object} staticRecords - Records data that need to be synchronized.
     */
    processStaticRecords(staticRecords) {
        return this.models.connectNewData(staticRecords);
    }

    /**
     * Apply synchronized dynamic records to the frontend.
     * @param {Object} dynamicRecords - Record write dates by ids and models.
     */
    async processDynamicRecords(dynamicRecords) {
        return this.models.connectNewData(dynamicRecords);
    }

    /**
     * Remove records deleted on the backend from the frontend and IndexedDB.
     * @param {Object} deletedRecords - Ids of inexisting records in the backend by models.
     */
    processDeletedRecords(deletedRecords) {
        for (const [model, ids] of Object.entries(deletedRecords)) {
            const records = this.models[model].readMany(ids).filter(Boolean);
            // Also evict the rows from IndexedDB, otherwise records deleted on
            // another device stay persisted locally and get re-loaded on the next
            // refresh (resurrecting orders that were deleted elsewhere).
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
     * Build the domain matching local open orders that have a server id.
     * @returns {Array} - Array of domain conditions.
     */
    constructOrdersDomain() {
        const dynamicModels = this.dynamicModels;
        const recordsToCheck = Array.from(dynamicModels).reduce((acc, model) => {
            const collection = this.models[model];
            // A dynamic model can be declared by an installed module without being
            // part of the current session's loaded data (e.g. preparation-display
            // models when the POS config has no preparation display). There is then
            // no collection to read and nothing to sync for it.
            if (!collection) {
                return acc;
            }
            acc[model] = collection.filter(
                (r) => !this.pos.data.opts.databaseTable[model]?.condition(r),
            );
            return acc;
        }, {});

        const recordIdsByModel = {};
        const domainByModel = Object.entries(recordsToCheck).reduce(
            (acc, [model, records]) => {
                const serverRecs = records.filter((r) => r.isSynced);
                const ids = serverRecs.map((r) => r.id);
                const config = this.pos.config;
                const domains = [];

                if (ids.length === 0 && model !== "pos.order") {
                    return acc;
                }

                recordIdsByModel[model] = ids;
                for (const record of serverRecs) {
                    const recordDateTime = record.write_date
                        .plus({ seconds: 1 })
                        .toUTC();
                    const recordDateTimeString = recordDateTime.toFormat(
                        "yyyy-MM-dd HH:mm:ss",
                        {
                            numberingSystem: "latn",
                        },
                    );

                    let domain = new Domain([
                        ["id", "=", record.id],
                        ["write_date", ">=", recordDateTimeString],
                    ]);

                    if (model === "pos.order") {
                        domain = Domain.or([
                            domain,
                            new Domain([
                                ["id", "=", record.id],
                                ["state", "!=", record.state],
                            ]),
                        ]);
                    }

                    domains.push(domain);
                }

                let domain = Domain.or(domains);
                if (model === "pos.order") {
                    domain = Domain.or([
                        domain,
                        new Domain([
                            ["id", "not in", ids],
                            ["state", "=", "draft"],
                            [
                                "config_id",
                                "in",
                                [config.id, ...config.raw.trusted_config_ids],
                            ],
                        ]),
                    ]);

                    acc[model] = domain.toList();
                }

                return acc;
            },
            {},
        );

        return { domain: domainByModel, recordIds: recordIdsByModel };
    }
}
