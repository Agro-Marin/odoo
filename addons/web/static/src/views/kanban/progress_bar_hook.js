// @ts-check
/** @odoo-module native */

/** @module @web/views/kanban/progress_bar_hook */

import { onWillDestroy, reactive } from "@odoo/owl";
import { Domain } from "@web/core/domain";
import { _t } from "@web/core/l10n/translation";
import { debounce } from "@web/core/utils/timing";
import {
    extractAggregatesFromGroupData,
    getAggregateSpecifications,
} from "@web/model/relational_model/utils";

/** @import { Group } from "@web/model/relational_model/group" */

const FALSE = Symbol("False");

const MOVE_RECONCILE_DELAY = 300;

/**
 * @type {{ activeBar: string | null, bars: Object[], total: number, isReady: boolean }}
 */
const EMPTY_GROUP_INFO = Object.freeze({
    activeBar: null,
    bars: [],
    total: 0,
    isReady: false,
});

/**
 * @param {Object[]} groups
 * @param {Object} groupByField
 * @param {*} value
 * @returns {Object}
 */
function _findGroup(groups, groupByField, value) {
    return groups.find((g) => g[groupByField.name] === value) || {};
}

/**
 * @param {string} fieldName
 * @param {Object[]} bars
 * @param {*} value
 * @returns {Array}
 */
function _createFilterDomain(fieldName, bars, value) {
    let filterDomain;
    if (value === FALSE) {
        const keys = bars.filter((x) => x.value !== FALSE).map((x) => x.value);
        filterDomain = ["!", [fieldName, "in", keys]];
    } else {
        filterDomain = [[fieldName, "=", value]];
    }
    return filterDomain;
}

/**
 * @param {Object[]} groups
 * @param {string[]} groupBy
 * @param {Object} fields
 * @returns {Object[]}
 */
function _groupsToAggregateValues(groups, groupBy, fields) {
    const groupByFieldName = groupBy[0].split(":")[0];
    return groups.map((g) => {
        const { aggregates, serverValue } = extractAggregatesFromGroupData(
            g,
            groupBy,
            fields,
        );
        return Object.assign(aggregates, { [groupByFieldName]: serverValue });
    });
}

class ProgressBarState {
    /**
     * @param {Object} progressAttributes
     * @param {Object} model
     * @param {Object[]} aggregateFields
     * @param {Object} [activeBars={}]
     */
    constructor(progressAttributes, model, aggregateFields, activeBars = {}) {
        this.progressAttributes = progressAttributes;
        this.model = model;
        this._groupsInfo = {};
        this._aggregateFields = aggregateFields;
        this.activeBars = activeBars;
        this._aggregateValues = [];
        this._pbCounts = null;
        this._pbEpoch = 0;
        this._aggEpoch = 0;
        /** @type {Map<*, number>} */
        this._groupAggEpochs = new Map();
        this._pendingBarDeselections = new Set();
        this._recordMoves = new Map();
    }

    /**
     * @param {Group} group
     * @returns {{ activeBar: string | null, bars: Object[], total: number, isReady: boolean }}
     */
    getGroupInfo(group) {
        if (this._pbCounts === null) {
            return EMPTY_GROUP_INFO;
        }
        if (!this._groupsInfo[group.id]) {
            this._seedGroupInfo(group);
        }
        return this._groupsInfo[group.id];
    }

    /**
     * @param {Group} group
     */
    _seedGroupInfo(group) {
        const aggValues = _findGroup(
            this._aggregateValues,
            group.groupByField,
            group.serverValue,
        );
        const index = this._aggregateValues.indexOf(aggValues);
        if (index > -1) {
            this._aggregateValues.splice(index, 1);
        }
        this._aggregateValues.push({
            ...group.aggregates,
            [group.groupByField.name]: group.serverValue,
        });
        const groupValue = this._getGroupValue(group);
        const pbCount = this._pbCounts[groupValue];
        const { fieldName, colors } = this.progressAttributes;
        const { selection: fieldSelection } = this.model.root.fields[fieldName];
        const selection = fieldSelection && Object.fromEntries(fieldSelection);
        const bars = Object.entries(colors).map(([value, color]) => {
            let string;
            if (selection) {
                string = selection[value];
            } else {
                string = String(value);
            }
            return {
                count: (pbCount && pbCount[value]) || 0,
                value,
                string,
                color,
            };
        });
        bars.push({
            count: Math.max(
                0,
                group.count - bars.map((r) => r.count).reduce((a, b) => a + b, 0),
            ),
            value: /** @type {any} */ (FALSE),
            string: _t("Other"),
            color: "200",
        });

        if (this.activeBars[group.serverValue]) {
            this.activeBars[group.serverValue].count =
                bars.find((x) => x.value === this.activeBars[group.serverValue].value)
                    ?.count ?? 0;

            if (this._aggregateFields.length) {
                this.activeBars[group.serverValue].aggregates = _findGroup(
                    this._aggregateValues,
                    group.groupByField,
                    group.serverValue,
                );
            }
        }

        const self = this;
        const progressBar = {
            get activeBar() {
                return self.activeBars[group.serverValue]?.value || null;
            },
            bars,
            total: bars.reduce((sum, bar) => sum + bar.count, 0),
            isReady: true,
        };

        this._groupsInfo[group.id] = progressBar;
    }

    /**
     * @param {Group} group
     * @param {Object} aggregateField
     * @returns {{ title: string, value: number, currencies?: Array }}
     */
    getAggregateValue(group, aggregateField) {
        const { groupByField, serverValue } = group;
        const title = aggregateField ? aggregateField.string : _t("Count");
        let value;
        if (!this.activeBars[serverValue]) {
            value = group.count;
            if (value && aggregateField) {
                value = _findGroup(this._aggregateValues, groupByField, serverValue)[
                    aggregateField.name
                ];
            }
        } else {
            value = this.activeBars[serverValue].count;
            if (value && aggregateField) {
                value =
                    this.activeBars[serverValue]?.aggregates &&
                    this.activeBars[serverValue]?.aggregates[aggregateField.name];
            }
        }
        value ||= 0;
        if (
            aggregateField &&
            aggregateField.type === "monetary" &&
            aggregateField.currency_field
        ) {
            const aggValues = _findGroup(
                this._aggregateValues,
                groupByField,
                serverValue,
            );
            const currencies = aggValues?.[aggregateField.currency_field];
            if (currencies?.length > 1) {
                return {
                    title,
                    value,
                    currencies,
                };
            }
            if (currencies?.[0]) {
                return {
                    title,
                    value,
                    currencies: [currencies[0]],
                };
            }
        }
        return { title, value };
    }

    /**
     * @param {string} groupId
     * @param {{ value: * }} bar
     */
    async selectBar(groupId, bar) {
        const group = this.model.root.groups.find((group) => group.id === groupId);
        const progressBar = this.getGroupInfo(group);
        const nextActiveBar = {};
        if (bar.value && this.activeBars[group.serverValue]?.value !== bar.value) {
            nextActiveBar.value = bar.value;
        } else {
            await group.applyFilter(undefined);
            delete this.activeBars[group.serverValue];
            group.model.notify();
            return;
        }
        const { bars } = progressBar;
        const filterDomain = _createFilterDomain(
            this.progressAttributes.fieldName,
            bars,
            nextActiveBar.value,
        );
        const proms = [];
        proms.push(
            group.applyFilter(filterDomain).then(() => {
                const groupInfo = this.getGroupInfo(group);
                nextActiveBar.count = groupInfo.bars.find(
                    (x) => x.value === nextActiveBar.value,
                ).count;
            }),
        );
        if (this._aggregateFields.length) {
            proms.push(this._updateAggregateGroup(group, bars, nextActiveBar));
        }
        await Promise.all(proms);
        this.activeBars[group.serverValue] = nextActiveBar;
        this.updateCounts(group);
    }

    /**
     * @param {Group} group
     * @param {Object[]} bars
     * @param {Object} activeBar
     * @returns {Promise<void>}
     */
    async _updateAggregateGroup(group, bars, activeBar) {
        const epoch = (this._groupAggEpochs.get(group.serverValue) || 0) + 1;
        this._groupAggEpochs.set(group.serverValue, epoch);
        const filterDomain = _createFilterDomain(
            this.progressAttributes.fieldName,
            bars,
            activeBar.value,
        );
        const { context, fields, groupBy, resModel } = this.model.root;
        const kwargs = { context };
        const aggregateSpecs = getAggregateSpecifications(this._aggregateFields);
        const domain = filterDomain
            ? Domain.and([group.groupDomain, filterDomain]).toList()
            : group.groupDomain;
        const groups = await this.model.orm.formattedReadGroup(
            resModel,
            domain,
            groupBy,
            aggregateSpecs,
            kwargs,
        );
        if (epoch !== this._groupAggEpochs.get(group.serverValue)) {
            return;
        }
        if (groups.length) {
            const groupByField = group.groupByField;
            const aggrValues = _groupsToAggregateValues(groups, groupBy, fields);
            activeBar.aggregates = _findGroup(
                aggrValues,
                groupByField,
                group.serverValue,
            );
        }
    }

    /**
     * @param {Group} group
     * @param {Object} [record]
     */
    updateCounts(group, record) {
        const move = record && this._recordMoves.get(record.id);
        if (move) {
            this._recordMoves.delete(record.id);
        }
        if (!(move && this._reconcileMove(record, move))) {
            this._updateProgressBar().catch((error) => console.error(error));
            if (this._aggregateFields.length) {
                this._updateAggregates().catch((error) => console.error(error));
                this.updateAggregateGroup(group);
            }
        }

        this._deselectActiveBars((group) => group.list.count === 0);
    }

    /**
     * @param {(group: Group, activeBar: Object) => boolean} shouldDeselect
     */
    _deselectActiveBars(shouldDeselect) {
        for (const group of this.model.root.groups) {
            const activeBar = this.activeBars[group.serverValue];
            if (
                !activeBar ||
                this._pendingBarDeselections.has(group.serverValue) ||
                !shouldDeselect(group, activeBar)
            ) {
                continue;
            }
            this._pendingBarDeselections.add(group.serverValue);
            this.selectBar(group.id, { value: null })
                .catch((error) => console.error(error))
                .finally(() => this._pendingBarDeselections.delete(group.serverValue));
        }
    }

    /**
     * @param {string} recordId
     * @param {string} sourceGroupId
     * @param {string} targetGroupId
     */
    registerRecordMove(recordId, sourceGroupId, targetGroupId) {
        if (this._recordMoves.has(recordId)) {
            return;
        }
        const groups = this.model.root.groups || [];
        const sourceGroup = groups.find((g) => g.id === sourceGroupId);
        const record = sourceGroup?.list.records.find((r) => r.id === recordId);
        this._recordMoves.set(recordId, {
            sourceGroupId,
            targetGroupId,
            sourceValue: record?.data[this.progressAttributes.fieldName],
        });
    }

    /**
     * @param {string} recordId
     */
    cancelRecordMove(recordId) {
        this._recordMoves.delete(recordId);
    }

    /**
     * @param {Object} record
     * @param {Object} move
     * @returns {boolean}
     */
    _reconcileMove(record, move) {
        const groups = this.model.root.groups || [];
        const sourceGroup = groups.find((g) => g.id === move.sourceGroupId);
        const targetGroup = groups.find((g) => g.id === move.targetGroupId);
        const { fieldName } = this.progressAttributes;
        if (
            this._pbCounts === null ||
            !sourceGroup ||
            !targetGroup ||
            !(fieldName in record.data) ||
            fieldName === this.model.root.groupByField.name
        ) {
            return false;
        }
        this._pbEpoch++;
        this._applyMoveDelta(sourceGroup, move.sourceValue, -1);
        this._applyMoveDelta(targetGroup, record.data[fieldName], +1);
        if (this._aggregateFields.length) {
            this._updateAggregatesForGroups([sourceGroup, targetGroup]).catch((error) =>
                console.error(error),
            );
            this.updateAggregateGroup(sourceGroup);
            this.updateAggregateGroup(targetGroup);
        }
        this._scheduleMoveReconcile();
        return true;
    }

    /**
     * @param {Group} group
     * @param {*} value
     * @param {number} delta
     */
    _applyMoveDelta(group, value, delta) {
        const { colors } = this.progressAttributes;
        const bucket = Object.keys(colors).find(
            (key) => key === value || key === String(value),
        );
        if (bucket) {
            const counts = (this._pbCounts[this._getGroupValue(group)] ||= {});
            counts[bucket] = Math.max(0, (counts[bucket] || 0) + delta);
        }
        const groupInfo = this._groupsInfo[group.id];
        if (!groupInfo) {
            return;
        }
        if (bucket) {
            const bar = groupInfo.bars.find((b) => b.value === bucket);
            if (bar) {
                bar.count = Math.max(0, bar.count + delta);
            }
        }
        const coloredCount = groupInfo.bars
            .filter((b) => b.value !== FALSE)
            .reduce((sum, b) => sum + b.count, 0);
        groupInfo.bars.find((b) => b.value === FALSE).count = Math.max(
            0,
            group.count - coloredCount,
        );
        groupInfo.total = groupInfo.bars.reduce((sum, bar) => sum + bar.count, 0);
        if (this.activeBars[group.serverValue]) {
            this.activeBars[group.serverValue].count =
                groupInfo.bars.find(
                    (x) => x.value === this.activeBars[group.serverValue].value,
                )?.count ?? 0;
        }
    }

    /**
     * @param {Group[]} groupsToUpdate
     * @returns {Promise<void>}
     */
    async _updateAggregatesForGroups(groupsToUpdate) {
        const epoch = ++this._aggEpoch;
        const { context, fields, groupBy, resModel } = this.model.root;
        const domain = Domain.or(groupsToUpdate.map((g) => g.groupDomain)).toList();
        const groups = await this.model.orm.formattedReadGroup(
            resModel,
            domain,
            groupBy,
            getAggregateSpecifications(this._aggregateFields),
            { context },
        );
        if (epoch !== this._aggEpoch) {
            return;
        }
        const aggrValues = _groupsToAggregateValues(groups, groupBy, fields);
        for (const group of groupsToUpdate) {
            const { groupByField, serverValue } = group;
            const entry = {
                ..._findGroup(aggrValues, groupByField, serverValue),
                [groupByField.name]: serverValue,
            };
            const index = this._aggregateValues.findIndex(
                (values) => values[groupByField.name] === serverValue,
            );
            if (index > -1) {
                this._aggregateValues[index] = entry;
            } else {
                this._aggregateValues.push(entry);
            }
        }
    }

    _scheduleMoveReconcile() {
        if (!this._moveReconcileDebounced) {
            this._moveReconcileDebounced = debounce(() => {
                this._updateProgressBar().catch((error) => console.error(error));
                if (this._aggregateFields.length) {
                    this._updateAggregates().catch((error) => console.error(error));
                    for (const group of this.model.root.groups || []) {
                        this.updateAggregateGroup(group);
                    }
                }
            }, MOVE_RECONCILE_DELAY);
        }
        this._moveReconcileDebounced();
    }

    _scheduleMembershipRetry() {
        if (!this._membershipRetryDebounced) {
            this._membershipRetryDebounced = debounce(() => {
                this._updateProgressBar().catch((error) => console.error(error));
            }, MOVE_RECONCILE_DELAY);
        }
        this._membershipRetryDebounced();
    }

    /**
     * @param {Group} group
     */
    updateAggregateGroup(group) {
        if (group && this.activeBars[group.serverValue]) {
            const { bars } = this.getGroupInfo(group);
            this._updateAggregateGroup(
                group,
                bars,
                this.activeBars[group.serverValue],
            ).catch((error) => console.error(error));
        }
    }

    async _updateAggregates() {
        const epoch = ++this._aggEpoch;
        const { context, fields, groupBy, domain, resModel } = this.model.root;
        const kwargs = { context };
        const groups = await this.model.orm.formattedReadGroup(
            resModel,
            domain,
            groupBy,
            getAggregateSpecifications(this._aggregateFields),
            kwargs,
        );
        if (epoch !== this._aggEpoch) {
            return;
        }
        this._aggregateValues = _groupsToAggregateValues(groups, groupBy, fields);
    }

    /**
     * @param {{ context: Object, domain: Array, groupBy: string[], resModel: string }} params
     * @returns {Promise<Object>}
     */
    _fetchProgressBarCounts({ context, domain, groupBy, resModel }) {
        const { colors, fieldName: field, help } = this.progressAttributes;
        return this.model.orm.call(resModel, "read_progress_bar", [], {
            domain,
            group_by: groupBy[0],
            progress_bar: { colors, field, help },
            context,
        });
    }

    async _updateProgressBar() {
        const { context, domain, groupBy, resModel } = this.model.root;
        if (groupBy.length) {
            const epoch = ++this._pbEpoch;
            const groupIds = new Set(this.model.root.groups.map((g) => g.id));
            const res = await this._fetchProgressBarCounts({
                context,
                domain,
                groupBy,
                resModel,
            });
            if (epoch !== this._pbEpoch) {
                return;
            }
            const currentIds = this.model.root.groups.map((g) => g.id);
            if (
                currentIds.length !== groupIds.size ||
                currentIds.some((id) => !groupIds.has(id))
            ) {
                this._scheduleMembershipRetry();
                return;
            }
            this._pbCounts = res;
            this._refreshBars();
        }
    }

    _refreshBars() {
        if (this._pbCounts === null) {
            return;
        }
        for (const group of this.model.root.groups) {
            if (group.isFolded) {
                continue;
            }
            const groupInfo = this.getGroupInfo(group);
            const counts = this._pbCounts[this._getGroupValue(group)];
            for (const bar of groupInfo.bars) {
                bar.count = (counts && counts[bar.value]) || 0;
            }
            groupInfo.bars.find((b) => b.value === FALSE).count = counts
                ? Math.max(
                      0,
                      group.count - Object.values(counts).reduce((a, b) => a + b, 0),
                  )
                : group.count;
            groupInfo.total = groupInfo.bars.reduce((sum, bar) => sum + bar.count, 0);
            if (this.activeBars[group.serverValue]) {
                this.activeBars[group.serverValue].count =
                    groupInfo.bars.find(
                        (x) => x.value === this.activeBars[group.serverValue].value,
                    )?.count ?? 0;
            }
        }
        this._deselectEmptyActiveBars();
    }

    _deselectEmptyActiveBars() {
        if (this._pbCounts === null) {
            return;
        }
        this._deselectActiveBars(
            (group, activeBar) =>
                !group.isFolded &&
                (this.getGroupInfo(group).bars.find((x) => x.value === activeBar.value)
                    ?.count || 0) === 0,
        );
    }

    /**
     * @param {{ context: Object, domain: Array, groupBy: string[], resModel: string }} params
     */
    async loadProgressBar({ context, domain, groupBy, resModel }) {
        if (groupBy.length) {
            const epoch = ++this._pbEpoch;
            const res = await this._fetchProgressBarCounts({
                context,
                domain,
                groupBy,
                resModel,
            });
            if (epoch !== this._pbEpoch) {
                return;
            }
            this._pbCounts = res;
        }
    }

    /**
     * @param {Group} group
     * @returns {number | undefined}
     */
    getGroupCount(group) {
        const progressBarInfo = this.getGroupInfo(group);
        if (progressBarInfo.activeBar) {
            return progressBarInfo.bars.find(
                (b) => b.value === progressBarInfo.activeBar,
            )?.count;
        }
    }

    _pruneGroupsInfo() {
        const groupIds = new Set(
            (this.model.root.groups || []).map((group) => group.id),
        );
        for (const id of Object.keys(this._groupsInfo)) {
            if (!groupIds.has(id)) {
                delete this._groupsInfo[id];
            }
        }
    }

    /**
     * @param {Group} group
     * @return string
     */
    _getGroupValue(group) {
        if (group.value === true) {
            return "True";
        } else if (group.value === false) {
            return "False";
        }
        return group.serverValue;
    }
}

/**
 * @param {Object} progressAttributes
 * @param {Object} model
 * @param {Object[]} aggregateFields
 * @param {Object} [activeBars]
 * @returns {ProgressBarState}
 */
export function useProgressBar(progressAttributes, model, aggregateFields, activeBars) {
    const progressBarState = reactive(
        new ProgressBarState(progressAttributes, model, aggregateFields, activeBars),
    );

    const onWillLoadRoot = model.hooks.lifecycle.onWillLoadRoot;
    let prom;
    model.hooks.lifecycle.onWillLoadRoot = (config) => {
        onWillLoadRoot(config);
        prom = progressBarState.loadProgressBar({
            context: config.context,
            domain: config.domain,
            groupBy: config.groupBy,
            resModel: config.resModel,
        });
    };
    const onRootLoaded = model.hooks.lifecycle.onRootLoaded;
    model.hooks.lifecycle.onRootLoaded = async (root) => {
        await onRootLoaded(root);
        progressBarState._pruneGroupsInfo();
        if (model.isReady) {
            return prom
                ?.then(() => progressBarState._refreshBars())
                .catch((error) => console.error(error));
        }
        prom?.then(() => progressBarState._deselectEmptyActiveBars()).catch((error) =>
            console.error(error),
        );
    };
    onWillDestroy(() => {
        model.hooks.lifecycle.onWillLoadRoot = onWillLoadRoot;
        model.hooks.lifecycle.onRootLoaded = onRootLoaded;
        progressBarState._moveReconcileDebounced?.cancel();
        progressBarState._membershipRetryDebounced?.cancel();
    });

    return progressBarState;
}
