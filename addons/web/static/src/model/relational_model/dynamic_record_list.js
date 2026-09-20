// @ts-check
/** @odoo-module native */

import { toRaw } from "@odoo/owl";
import { shallowEqual } from "@web/core/utils/collections/objects";

import { DynamicList } from "./dynamic_list.js";

/** @import { ListInsertion } from "./editable_list_datapoint.js" */
/** @import { RelationalRecord } from "./record.js" */
export class DynamicRecordList extends DynamicList {
    static type = "DynamicRecordList";

    /**
     * @param {import("./relational_model").RelationalModelConfig} config
     * @param {Object} data
     * @param {{ previousRoot?: any }} [options]
     */
    setup(config, data, { previousRoot } = {}) {
        super.setup(config);
        /** @type {RelationalRecord[]} */
        this._records =
            previousRoot instanceof DynamicRecordList &&
            previousRoot.resModel === this.resModel
                ? previousRoot._records
                : [];
        this.setData(data);
    }

    setData(data) {
        const reusable = new Map();
        for (const record of this._records) {
            if (this._canReuseRecord(record)) {
                reusable.set(record.resId, record);
            }
        }
        /** @type {RelationalRecord[]} */
        this._records = data.records.map((values) => {
            const existing = values.id ? reusable.get(values.id) : undefined;
            if (!existing) {
                return this._createRecordDatapoint(values);
            }
            reusable.delete(values.id);
            existing.selected = false;
            existing.setData(values);
            return existing;
        });
        this._adoptCount(data);
        this._selectDomain(this.isDomainSelected);
    }

    /**
     * A reloaded row keeps its datapoint, and so its components, when it still
     * describes the same record under the same field set; anything the user
     * touched, or a row built for another config, is rebuilt. Config members
     * are compared raw: the list and its records reach them through different
     * reactive proxies of one object.
     *
     * @param {RelationalRecord} record
     * @returns {boolean}
     */
    _canReuseRecord(record) {
        const { config } = record;
        return (
            Boolean(record.resId) &&
            !record.manuallyAdded &&
            !record.isInEdition &&
            !record.dirty &&
            toRaw(config.activeFields) === toRaw(this.activeFields) &&
            toRaw(config.fields) === toRaw(this.fields) &&
            shallowEqual(config.context, this.context)
        );
    }

    get records() {
        return this._records;
    }

    get hasData() {
        return this.count > 0;
    }

    /**
     * @param {number} resId
     * @param {ListInsertion} [options]
     * @returns {Promise<RelationalRecord>}
     */
    addExistingRecord(resId, { position } = {}) {
        return this.model.mutex.exec(async () => {
            const record = this._createRecordDatapoint({});
            await record.loadLocked({ resId });
            this.addRecord(record, position === "top" ? 0 : this.records.length);
            return record;
        });
    }

    /**
     * @param {ListInsertion} [options]
     * @returns {Promise<RelationalRecord>}
     */
    addNewRecord({ position } = {}) {
        return this.model.mutex.exec(async () => {
            await this._leaveSampleMode();
            return this._addNewRecord(position === "top");
        });
    }

    /** @type {DynamicList["clearSampleData"]} */
    clearSampleData() {
        this.count = 0;
        this._records = [];
    }

    async fetchCount() {
        this.count = await this.model.fetchExactCount(this.config);
        this.hasLimitedCount = false;
        return this.count;
    }

    async resequence(movedRecordId, targetRecordId) {
        return this.model.mutex.exec(
            async () =>
                await this.resequenceLocked(
                    this.records,
                    this.resModel,
                    movedRecordId,
                    targetRecordId,
                ),
        );
    }

    async _addNewRecord(atFirstPosition) {
        const values = await this.model.loadNewRecord(
            /** @type {any} */ ({
                resModel: this.resModel,
                activeFields: this.activeFields,
                fields: this.fields,
                context: this.context,
            }),
        );
        const record = this._createRecordDatapoint(values, "edit");
        this.addRecord(record, atFirstPosition ? 0 : this.records.length);
        return record;
    }

    addRecord(record, index) {
        this.records.splice(
            Number.isInteger(index) ? index : this.records.length,
            0,
            record,
        );
        this.count++;
    }

    /**
     * @param {Record<string, any>} data
     * @param {"edit" | "readonly"} [mode]
     */
    _createRecordDatapoint(data, mode = "readonly") {
        return new this.model.Class.Record(
            this.model,
            /** @type {any} */ ({
                context: this.context,
                activeFields: this.activeFields,
                resModel: this.resModel,
                fields: this.fields,
                resId: data.id || false,
                resIds: data.id ? [data.id] : [],
                isMonoRecord: true,
                mode,
            }),
            data,
            { manuallyAdded: !data.id },
        );
    }

    _getDPresId(record) {
        return record.resId;
    }

    _getDPFieldValue(record, handleField) {
        return record.data[handleField];
    }

    async loadLocked(offset, limit, orderBy, domain) {
        await this.model.reloadWithConfig(
            this.config,
            { offset, limit, orderBy, domain },
            { commit: this.setData.bind(this) },
        );
    }

    removeRecords(recordIds) {
        const idSet = new Set(recordIds);
        const keptRecords = this.records.filter((r) => !idSet.has(r.id));
        this.count -= this.records.length - keptRecords.length;
        this._records = keptRecords;
        if (this.offset && !this.records.length) {
            const offset = Math.max(this.offset - this.limit, 0);
            this.model.patchConfig(this.config, { offset });
        }
    }

    _selectDomain(value) {
        if (value) {
            this.records.forEach((r) => (r.selected = true));
        }
        super._selectDomain(value);
    }

    /** @param {{ length: number }} data */
    _adoptCount(data) {
        const length = data.length;
        if (length >= this.config.countLimit + 1) {
            this.hasLimitedCount = true;
            this.count = this.config.countLimit;
        } else {
            this.hasLimitedCount = false;
            this.count = length;
        }
    }
}
