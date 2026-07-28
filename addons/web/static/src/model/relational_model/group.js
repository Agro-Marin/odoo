// @ts-check
/** @odoo-module native */

/** @module @web/model/relational_model/group - Single group node within a grouped list, holding aggregates and a nested record list */

import { Domain } from "@web/core/domain";

import { DataPoint } from "./datapoint.js";
/** @import { RelationalModelConfig } from "./relational_model.js" */

export class Group extends DataPoint {
    static type = "Group";

    /**
     * @param {RelationalModelConfig & { groupByFieldName: string, list: any, record?: any }} config
     * @param {Record<string, any>} data
     */
    setup(config, data) {
        super.setup(config, data);
        this.groupByField = this.fields[config.groupByFieldName];
        this.range = data.range;
        this._rawValue = data.rawValue;
        /** @type {number} */
        this.count = data.count;
        this.value = data.value;
        this.serverValue = data.serverValue;
        this.displayName = data.displayName;
        this.aggregates = data.aggregates;
        let List;
        if (config.list.groupBy.length) {
            List = this.model.Class.DynamicGroupList;
        } else {
            List = this.model.Class.DynamicRecordList;
        }
        config.list.isGroupList = true;
        /** @type {any} DynamicRecordList or DynamicGroupList depending on groupBy depth */
        this.list = new List(this.model, config.list, data);
        this._useGroupCountForList();
        if (config.record) {
            config.record.context = {
                ...config.record.context,
                ...config.context,
            };
            this.record = new this.model.Class.Record(
                this.model,
                config.record,
                data.values,
            );
        }
    }

    get groupDomain() {
        return this.config.initialDomain;
    }
    get hasData() {
        return this.count > 0;
    }
    get isFolded() {
        return this.config.isFolded;
    }
    get records() {
        return this.list.records;
    }

    async addExistingRecord(resId, atFirstPosition = false) {
        const record = await this.list.addExistingRecord(resId, atFirstPosition);
        this.count++;
        return record;
    }

    async addNewRecord(_unused, atFirstPosition = false) {
        const canProceed = await this.model.root.leaveEditMode();
        if (canProceed) {
            const record = await this.list.addNewRecord(atFirstPosition);
            if (record) {
                this.count++;
            }
        }
    }

    async applyFilter(filter) {
        if (filter) {
            await this.list.load({
                domain: Domain.and([this.groupDomain, filter]).toList(),
            });
        } else {
            await this.list.load({ domain: this.groupDomain });
            this.count = this.list.isGrouped ? this.list.recordCount : this.list.count;
        }
        this.model._patchConfig(this.config, { extraDomain: filter });
    }

    deleteRecords(records) {
        return this.model.mutex.exec(() => this._deleteRecords(records));
    }

    toggle() {
        return this.model.mutex.exec(() => this._toggle());
    }

    async _toggle() {
        if (this.config.isFolded) {
            await this.list._load(
                this.list.offset,
                this.list.limit,
                this.list.orderBy,
                this.list.domain,
            );
        }
        this._useGroupCountForList();
        this.model._patchConfig(this.config, {
            isFolded: !this.config.isFolded,
        });
    }

    _addRecord(record, index) {
        if (record.resId && this.list.records.some((r) => r.resId === record.resId)) {
            return;
        }
        this.list._addRecord(record, index);
        this.count++;
    }

    async _deleteRecords(records) {
        const unlinked = await this.list._deleteRecords(records);
        if (unlinked) {
            this.count -= records.length;
        }
        return unlinked;
    }

    /**
     * ``web_search_read`` caps its count at ``countLimit`` (see
     * DEFAULT_COUNT_LIMIT); the per-group count from ``formatted_read_group``
     * is not capped. Where the list's number is the capped one, adopt the
     * group's.
     *
     * Asks the list whether it capped, rather than inferring it by comparing
     * ``count`` to ``countLimit``. That comparison answered correctly only by
     * accident: a group's list config carries no ``countLimit`` until its first
     * ``_loadData``, so on the initial (read_group-embedded) load it compared a
     * number against ``undefined`` — false, which happens to be the right
     * answer there because that count came from read_group and was never
     * capped. ``hasLimitedCount`` is set by ``_updateCount`` precisely when it
     * truncated, so it states the condition instead of re-deriving it.
     */
    _useGroupCountForList() {
        if (!this.list.isGrouped && this.list.hasLimitedCount) {
            this.list.count = this.count;
        }
    }

    /**
     * Synchronous on purpose: ``DynamicList._leaveEditMode`` drops an abandoned
     * new row through this without awaiting, and reads ``this.editedRecord``
     * on the very next line. An ``async`` signature over a fully synchronous
     * body only made that call site read as a race it never was.
     *
     * @param {(string | number)[]} recordIds
     */
    _removeRecords(recordIds) {
        const idsToRemove = recordIds.filter((id) =>
            this.list.records.some((r) => r.id === id),
        );
        this.list._removeRecords(idsToRemove);
        this.count -= idsToRemove.length;
    }
}
