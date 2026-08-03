// @ts-check
/** @odoo-module native */

/** @module @web/views/kanban/progress_bar_hook */

import { onWillDestroy, reactive } from "@odoo/owl";
import { Domain } from "@web/core/domain";
import { _t } from "@web/core/translation";
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
 * Identity key for a group's server value.
 *
 * `getGroupServerValue` wraps many2many values in a freshly allocated array, so
 * two server values denoting the same group are never `===`. Every internal map
 * in this module is therefore keyed by this canonical string rather than by the
 * server value itself.
 *
 * @param {*} serverValue
 * @returns {string}
 */
function groupKey(serverValue) {
    return JSON.stringify(serverValue ?? false);
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
 * @returns {Map<string, Object>} aggregates by {@link groupKey}
 */
function _groupsToAggregatesByKey(groups, groupBy, fields) {
    return new Map(
        groups.map((g) => {
            const { aggregates, serverValue } = extractAggregatesFromGroupData(
                g,
                groupBy,
                fields,
            );
            return [groupKey(serverValue), aggregates];
        }),
    );
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
        /** @type {Record<string, Object>} keyed by {@link groupKey} */
        this.activeBars = activeBars;
        /** @type {Map<string, Object>} aggregates by {@link groupKey} */
        this._aggregatesByKey = new Map();
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
     * Seeds every current group up front. `getGroupInfo` is read from render
     * (kanban header / renderer), and this state is `reactive`: seeding lazily
     * from there is a write to a subscribed object mid-render, which costs an
     * extra render pass per group. Called once per load instead.
     */
    _seedAllGroups() {
        if (this._pbCounts === null) {
            return;
        }
        for (const group of this.model.root.groups || []) {
            if (!this._groupsInfo[group.id]) {
                this._seedGroupInfo(group);
            }
        }
    }

    /**
     * @param {Group} group
     */
    _seedGroupInfo(group) {
        const key = groupKey(group.serverValue);
        this._aggregatesByKey.set(key, { ...group.aggregates });
        const pbCount = this._pbCounts[this._pbCountKey(group)];
        const { fieldName, colors } = this.progressAttributes;
        const { selection: fieldSelection } = this.model.root.fields[fieldName];
        const selection = fieldSelection && Object.fromEntries(fieldSelection);
        const bars = Object.entries(colors).map(([value, color]) => ({
            count: (pbCount && pbCount[value]) || 0,
            value,
            string: selection ? selection[value] : String(value),
            color,
        }));
        bars.push({
            count: 0,
            value: /** @type {any} */ (FALSE),
            string: _t("Other"),
            color: "200",
        });

        const activeBar = this.activeBars[key];
        if (activeBar && this._aggregateFields.length) {
            activeBar.aggregates = this._aggregatesByKey.get(key);
        }

        const self = this;
        this._groupsInfo[group.id] = {
            get activeBar() {
                return self.activeBars[key]?.value || null;
            },
            bars,
            total: 0,
            isReady: true,
        };
        this._recomputeTotals(group);
    }

    /**
     * Single source of truth for the derived counts: the "Other" bucket, the
     * group total and the active bar's count. Every path that mutates a bar
     * count funnels through here so the bars can never disagree.
     *
     * @param {Group} group
     */
    _recomputeTotals(group) {
        const groupInfo = this._groupsInfo[group.id];
        if (!groupInfo) {
            return;
        }
        const coloredCount = groupInfo.bars
            .filter((bar) => bar.value !== FALSE)
            .reduce((sum, bar) => sum + bar.count, 0);
        const otherBar = groupInfo.bars.find((bar) => bar.value === FALSE);
        if (otherBar) {
            otherBar.count = Math.max(0, group.count - coloredCount);
        }
        groupInfo.total = groupInfo.bars.reduce((sum, bar) => sum + bar.count, 0);
        const activeBar = this.activeBars[groupKey(group.serverValue)];
        if (activeBar) {
            activeBar.count =
                groupInfo.bars.find((bar) => bar.value === activeBar.value)?.count ?? 0;
        }
    }

    /**
     * @param {Group} group
     * @param {Object} aggregateField
     * @returns {{ title: string, value: number, currencies?: Array }}
     */
    getAggregateValue(group, aggregateField) {
        const key = groupKey(group.serverValue);
        const activeBar = this.activeBars[key];
        const title = aggregateField ? aggregateField.string : _t("Count");
        let value;
        if (!activeBar) {
            value = group.count;
            if (value && aggregateField) {
                value = this._aggregatesByKey.get(key)?.[aggregateField.name];
            }
        } else {
            value = activeBar.count;
            if (value && aggregateField) {
                value = activeBar.aggregates?.[aggregateField.name];
            }
        }
        value ||= 0;
        if (
            aggregateField &&
            aggregateField.type === "monetary" &&
            aggregateField.currency_field
        ) {
            const currencies =
                this._aggregatesByKey.get(key)?.[aggregateField.currency_field];
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
        const key = groupKey(group.serverValue);
        if (bar.value && this.activeBars[key]?.value !== bar.value) {
            nextActiveBar.value = bar.value;
        } else {
            await group.applyFilter(undefined);
            delete this.activeBars[key];
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
        this.activeBars[key] = nextActiveBar;
        this.updateCounts(group);
    }

    /**
     * @param {Group} group
     * @param {Object[]} bars
     * @param {Object} activeBar
     * @returns {Promise<void>}
     */
    async _updateAggregateGroup(group, bars, activeBar) {
        const key = groupKey(group.serverValue);
        const epoch = (this._groupAggEpochs.get(key) || 0) + 1;
        this._groupAggEpochs.set(key, epoch);
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
        if (epoch !== this._groupAggEpochs.get(key)) {
            return;
        }
        if (groups.length) {
            activeBar.aggregates =
                _groupsToAggregatesByKey(groups, groupBy, fields).get(key) || {};
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
            const key = groupKey(group.serverValue);
            const activeBar = this.activeBars[key];
            if (
                !activeBar ||
                this._pendingBarDeselections.has(key) ||
                !shouldDeselect(group, activeBar)
            ) {
                continue;
            }
            this._pendingBarDeselections.add(key);
            this.selectBar(group.id, { value: null })
                .catch((error) => console.error(error))
                .finally(() => this._pendingBarDeselections.delete(key));
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
            const counts = (this._pbCounts[this._pbCountKey(group)] ||= {});
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
        this._recomputeTotals(group);
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
        const aggregatesByKey = _groupsToAggregatesByKey(groups, groupBy, fields);
        for (const group of groupsToUpdate) {
            const key = groupKey(group.serverValue);
            this._aggregatesByKey.set(key, aggregatesByKey.get(key) || {});
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
        const activeBar = group && this.activeBars[groupKey(group.serverValue)];
        if (activeBar) {
            const { bars } = this.getGroupInfo(group);
            this._updateAggregateGroup(group, bars, activeBar).catch((error) =>
                console.error(error),
            );
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
        this._aggregatesByKey = _groupsToAggregatesByKey(groups, groupBy, fields);
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
            const counts = this._pbCounts[this._pbCountKey(group)];
            for (const bar of groupInfo.bars) {
                if (bar.value !== FALSE) {
                    bar.count = (counts && counts[bar.value]) || 0;
                }
            }
            this._recomputeTotals(group);
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
     * Key into `_pbCounts`, which is the raw `read_progress_bar` response and
     * therefore uses the SERVER's group-value spelling — not {@link groupKey}.
     *
     * @param {Group} group
     * @return string
     */
    _pbCountKey(group) {
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

    let prom;
    const unsubscribe = [
        model.subscribeLifecycle("onWillLoadRoot", (config) => {
            prom = progressBarState.loadProgressBar({
                context: config.context,
                domain: config.domain,
                groupBy: config.groupBy,
                resModel: config.resModel,
            });
        }),
        model.subscribeLifecycle("onRootLoaded", async () => {
            progressBarState._pruneGroupsInfo();
            try {
                await prom;
            } catch (error) {
                console.error(error);
                return;
            }
            progressBarState._seedAllGroups();
            if (model.isReady) {
                progressBarState._refreshBars();
            } else {
                progressBarState._deselectEmptyActiveBars();
            }
        }),
    ];
    onWillDestroy(() => {
        unsubscribe.forEach((stop) => stop());
        progressBarState._moveReconcileDebounced?.cancel();
        progressBarState._membershipRetryDebounced?.cancel();
    });

    return progressBarState;
}
