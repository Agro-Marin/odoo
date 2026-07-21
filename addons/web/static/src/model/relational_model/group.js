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
        // Mark the nested list's config as group-owned. Every group list —
        // whether seeded by the web_read_group postprocessor or by
        // ``DynamicGroupList._createGroup`` — is instantiated here, and always
        // before its first client-side load (page 1 comes from web_read_group
        // itself), so this is the single authoritative site for the flag.
        // ``RelationalModel._loadUngroupedList`` relies on it to append the
        // ``id`` order tiebreak that ``web_read_group`` applies server-side to
        // a group's ``__records`` (and that a root/ungrouped list must NOT get).
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

    // -------------------------------------------------------------------------
    // Getters
    // -------------------------------------------------------------------------

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

    // -------------------------------------------------------------------------
    // Public
    // -------------------------------------------------------------------------

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
        // Serialize on the model mutex like every sibling verb: ``_toggle``
        // reads ``isFolded``, awaits a load, then patches the flipped flag —
        // read and patch straddle an await, so an un-serialized double-click on
        // the header could read a stale ``isFolded`` mid-load and end folded
        // opposite to the last click (plus a duplicate load).
        return this.model.mutex.exec(() => this._toggle());
    }

    // -------------------------------------------------------------------------
    // Protected
    // -------------------------------------------------------------------------

    async _toggle() {
        if (this.config.isFolded) {
            // Call the PROTECTED ``_load`` (not public ``list.load()``, which
            // re-takes ``model.mutex`` and would deadlock inside this
            // mutex.exec) with the same defaults ``load()`` derives from an
            // empty params bag.
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
        // Dedupe by resId: a stale source-list reload racing this add (two rapid
        // cross-group kanban drags, or a revert after an un-mutexed reload)
        // rebuilds the list with FRESH datapoints, so a datapoint-id check would
        // miss the duplicate and the same card would render in two columns. Skip
        // when a record with this resId is already present. New records carry no
        // resId (only a virtualId), so they are never deduped.
        if (record.resId && this.list.records.some((r) => r.resId === record.resId)) {
            return;
        }
        this.list._addRecord(record, index);
        this.count++;
    }

    async _deleteRecords(records) {
        // Only decrement when the delegate actually unlinked: a vetoed unlink
        // (``DynamicList._deleteRecords`` returns ``false`` before reloading)
        // must not shrink the group count, which would then never self-correct
        // (no reload follows a veto).
        const unlinked = await this.list._deleteRecords(records);
        if (unlinked) {
            this.count -= records.length;
        }
        return unlinked;
    }

    /**
     * The count returned by web_search_read is limited (see DEFAULT_COUNT_LIMIT). However, the one
     * returned by formatted_read_group, for each group, isn't. So in the grouped case, it might happen
     * that the group count is more accurate than the list one. It that case, we use it on the list.
     */
    _useGroupCountForList() {
        if (!this.list.isGrouped && this.list.count === this.list.config.countLimit) {
            this.list.count = this.count;
        }
    }

    async _removeRecords(recordIds) {
        const idsToRemove = recordIds.filter((id) =>
            this.list.records.some((r) => r.id === id),
        );
        this.list._removeRecords(idsToRemove);
        this.count -= idsToRemove.length;
    }
}
