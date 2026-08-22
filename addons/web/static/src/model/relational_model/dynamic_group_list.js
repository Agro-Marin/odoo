// @ts-check
/** @odoo-module native */

import { Domain } from "@web/core/domain";

import { DynamicList } from "./dynamic_list.js";
import { getGroupServerValue } from "./field_values.js";

/** @import { DynamicListContract } from "./dynamic_list_contract.js" */
/** @import { RelationalRecord } from "./record.js" */

export const MOVABLE_RECORD_TYPES = [
    "char",
    "boolean",
    "integer",
    "selection",
    "many2one",
];

export class DynamicGroupList extends DynamicList {
    static type = "DynamicGroupList";

    /**
     * @type {DynamicList["setup"]}
     */
    setup(_config, data) {
        super.setup(_config);

        this.isGrouped = true;
        /** @type {number | null} */
        this._nbRecordsMatchingDomain = null;
        this._countedDomainKey = undefined;
        this._setData(/** @type {any} */ (data));
    }

    /**
     * @param {{ groups: any[], length: number, [key: string]: any }} data
     */
    _setData(data) {
        if (
            this._nbRecordsMatchingDomain !== null &&
            JSON.stringify(this.domain) !== this._countedDomainKey
        ) {
            this._nbRecordsMatchingDomain = null;
        }
        /** @type {import("./group").Group[]} */
        this.groups = data.groups.map((g) => this._createGroupDatapoint(g));
        this.count = data.length;
        this._selectDomain(this.isDomainSelected);
    }

    get groupBy() {
        return this.config.groupBy;
    }

    get groupByField() {
        return this.fields[this.groupBy[0].split(":")[0]];
    }

    get hasData() {
        return this.groups.some((group) => group.hasData);
    }

    get isRecordCountTrustable() {
        return this.count <= this.limit || this._nbRecordsMatchingDomain !== null;
    }

    /**
     * @returns {RelationalRecord[]}
     */
    get records() {
        return this.groups
            .filter((group) => !group.isFolded)
            .flatMap((group) => group.records);
    }

    /**
     * @returns {number}
     */
    get recordCount() {
        if (this._nbRecordsMatchingDomain !== null) {
            return this._nbRecordsMatchingDomain;
        }
        return this.groups.reduce((acc, group) => acc + group.count, 0);
    }

    /**
     * @type {DynamicList["clearSampleData"]}
     */
    clearSampleData() {
        this.count = 0;
        this.groups = [];
    }

    /**
     * @param {string} groupName
     * @param {string} [foldField]
     */
    async createGroup(groupName, foldField) {
        if (!this.groupByField || this.groupByField.type !== "many2one") {
            throw new Error("Cannot create a group on a non many2one group field");
        }

        await this.model.mutex.exec(() => this._createGroup(groupName, foldField));
    }

    async deleteGroups(groups) {
        await this.model.mutex.exec(() => this._deleteGroups(groups));
    }

    /**
     * @param {string} dataRecordId
     * @param {string} dataGroupId
     * @param {string} refId
     * @param {string} targetGroupId
     */
    async moveRecord(dataRecordId, dataGroupId, refId, targetGroupId) {
        const targetGroup = this.groups.find((g) => g.id === targetGroupId);
        if (dataGroupId === targetGroupId) {
            await targetGroup.list._resequence(
                targetGroup.list.records,
                this.resModel,
                dataRecordId,
                refId,
            );
            return;
        }

        const sourceGroup = this.groups.find((g) => g.id === dataGroupId);
        const sourceRecords = sourceGroup.list.records;
        const oldIndex = sourceRecords.findIndex((r) => r.id === dataRecordId);
        const record = sourceRecords[oldIndex];
        const refIndex = targetGroup.list.records.findIndex((r) => r.id === refId);

        const sourceList = sourceGroup.list;
        const mustReloadSourceList =
            sourceList.count > sourceList.offset + sourceList.limit;

        sourceGroup._removeRecords([record.id]);
        targetGroup._addRecord(record, refIndex + 1);
        let value = targetGroup.value;
        if (targetGroup.groupByField.type === "many2one") {
            value = value
                ? { id: value, display_name: targetGroup.displayName }
                : false;
        }

        const sourceGroupValue = sourceGroup.value;
        const targetGroupValue = targetGroup.value;
        const revert = () =>
            this.model.mutex.exec(() => {
                const currentTargetGroup = this.groups.find(
                    (g) => g.value === targetGroupValue,
                );
                const currentSourceGroup = this.groups.find(
                    (g) => g.value === sourceGroupValue,
                );
                currentTargetGroup?._removeRecords([record.id]);
                currentSourceGroup?._addRecord(record, oldIndex);
                record._discard();
            });
        try {
            const changes = { [targetGroup.groupByField.name]: value };
            const res = await record.update(changes, { save: true });
            if (!res) {
                return revert();
            }
        } catch (e) {
            await revert();
            throw e;
        }

        const proms = [];
        if (mustReloadSourceList) {
            const { offset, limit, orderBy, domain } = sourceGroup.list;
            proms.push(
                this.model.mutex.exec(() =>
                    sourceGroup.list._load(offset, limit, orderBy, domain),
                ),
            );
        }
        if (!targetGroup.isFolded) {
            /** @type {DynamicListContract & { records: any[] }} */
            const targetList = targetGroup.list;
            const records = targetList.records;
            proms.push(
                targetList._resequence(records, this.resModel, dataRecordId, refId),
            );
        }
        return Promise.all(proms);
    }

    async resequence(movedGroupId, targetGroupId) {
        if (!this.groupByField || this.groupByField.type !== "many2one") {
            throw new Error("Cannot resequence a group on a non many2one group field");
        }

        return this.model.mutex.exec(async () => {
            await this._resequence(
                this.groups,
                this.groupByField.relation,
                movedGroupId,
                targetGroupId,
            );
        });
    }

    async selectDomain(value) {
        return this.model.mutex.exec(async () => {
            await this._ensureCorrectRecordCount();
            this._selectDomain(value);
        });
    }

    async sortBy(fieldName) {
        if (!this.groups.length) {
            return;
        }
        if (this.groups.every((group) => group.isFolded)) {
            if (this.groupByField.name !== fieldName) {
                if (!(fieldName in this.groups[0].aggregates)) {
                    return;
                }
            }
        }
        return super.sortBy(fieldName);
    }

    /**
     * @param {string} groupName
     * @param {string | false} foldField
     * @returns {Promise<number>}
     */
    async _createGroupRecord(groupName, foldField) {
        const [id] = await this.model.orm.call(
            this.groupByField.relation,
            "name_create",
            [groupName],
            { context: this.context },
        );
        if (foldField) {
            await this.model.orm.write(
                this.groupByField.relation,
                [id],
                { [foldField]: true },
                { context: this.context },
            );
        }
        return id;
    }

    /**
     * @param {number} id
     * @param {string | false} foldField
     * @returns {{ domain: any, groupBy: string[] }}
     */
    _addGroupConfig(id, foldField) {
        const commonConfig = {
            resModel: this.config.resModel,
            fields: this.config.fields,
            activeFields: this.config.activeFields,
            fieldsToAggregate: this.config.fieldsToAggregate,
        };
        const context = {
            ...this.context,
            [`default_${this.groupByField.name}`]: id,
        };
        const domain = Domain.and([
            this.domain,
            [[this.groupByField.name, "=", id]],
        ]).toList();
        const groupBy = this.groupBy.slice(1);
        const nextConfigGroups = { ...this.config.groups };
        nextConfigGroups[id] = {
            ...commonConfig,
            context,
            groupByFieldName: this.groupByField.name,
            isFolded: Boolean(foldField),
            value: id,
            extraDomain: false,
            initialDomain: domain,
            list: {
                ...commonConfig,
                context,
                domain,
                groupBy,
                orderBy: this.orderBy,
                limit: this.model.initialLimit,
                offset: 0,
            },
        };
        this.model._patchConfig(this.config, { groups: nextConfigGroups });
        return { domain, groupBy };
    }

    /**
     * @param {number} id
     * @param {string} groupName
     * @param {string[]} groupBy
     * @returns {Record<string, any>}
     */
    _emptyGroupData(id, groupName, groupBy) {
        /** @type {Record<string, any>} */
        const data = {
            aggregates: {},
            count: 0,
            length: 0,
            value: id,
            serverValue: getGroupServerValue(this.groupByField, id),
            displayName: groupName,
            rawValue: [id, groupName],
        };
        if (groupBy.length) {
            data.groups = [];
        } else {
            data.records = [];
        }
        return data;
    }

    /**
     * @param {string} groupName
     * @param {string | false} [foldField]
     */
    async _createGroup(groupName, foldField = false) {
        const id = await this._createGroupRecord(groupName, foldField);
        const lastGroup = this.groups.at(-1);
        const { groupBy } = this._addGroupConfig(id, foldField);
        const group = this._createGroupDatapoint(
            this._emptyGroupData(id, groupName, groupBy),
        );

        if (lastGroup) {
            const groups = [...this.groups, group];
            await this._resequence(
                groups,
                this.groupByField.relation,
                group.id,
                lastGroup.id,
            );
            this.groups = groups;
        } else {
            this.groups.push(group);
        }
        this.count++;
    }

    _createGroupDatapoint(data) {
        return new this.model.Class.Group(
            this.model,
            /** @type {any} */ (this.config.groups[data.value]),
            data,
        );
    }

    async _deleteGroups(groups) {
        const shouldReload = groups.some((g) => g.count > 0);
        const succeeded = await this._unlinkGroups(groups);
        if (succeeded === false) {
            return;
        }
        const configGroups = { ...this.config.groups };
        for (const group of groups) {
            delete configGroups[group.value];
        }
        if (shouldReload) {
            await this.model._reloadWithConfig(
                this.config,
                { groups: configGroups },
                { commit: /** @type {any} */ (this._setData.bind(this)) },
            );
        } else {
            for (const group of groups) {
                this._removeGroup(group);
            }
            this.model._patchConfig(this.config, { groups: configGroups });
        }
    }

    async _ensureCorrectRecordCount() {
        if (!this.isRecordCountTrustable) {
            this._countedDomainKey = JSON.stringify(this.domain);
            this._nbRecordsMatchingDomain = await this.model.orm.searchCount(
                this.resModel,
                this.domain,
                { limit: this.model.initialCountLimit, context: this.context },
            );
        }
    }

    _getDPresId(group) {
        return group.value;
    }

    _getDPFieldValue(group, handleField) {
        return group[handleField];
    }

    async _load(offset, limit, orderBy, domain) {
        await this.model._reloadWithConfig(
            this.config,
            { offset, limit, orderBy, domain },
            { commit: /** @type {any} */ (this._setData.bind(this)) },
        );
        if (this.isDomainSelected) {
            await this._ensureCorrectRecordCount();
        }
    }

    /** @param {import('./group.js').Group} group */
    _removeGroup(group) {
        const index = this.groups.findIndex((g) => g.id === group.id);
        if (index === -1) {
            return;
        }
        this.groups.splice(index, 1);
        this.count--;
    }

    /** @param {(string | number)[]} recordIds */
    _removeRecords(recordIds) {
        for (const group of this.groups) {
            group._removeRecords(recordIds);
        }
    }

    /** @param {boolean} value */
    _selectDomain(value) {
        for (const group of this.groups) {
            group.list._selectDomain(value);
        }
        super._selectDomain(value);
    }

    async _toggleSelection() {
        if (!this.records.length) {
            if (!this.isDomainSelected) {
                await this._ensureCorrectRecordCount();
                this._selectDomain(true);
            } else {
                this._selectDomain(false);
            }
        } else {
            super._toggleSelection();
        }
    }

    /** @param {import('./group.js').Group[]} groups */
    _unlinkGroups(groups) {
        const groupResIds = groups.map((g) => g.value);
        return this.model.orm.unlink(this.groupByField.relation, groupResIds, {
            context: this.context,
        });
    }
}
