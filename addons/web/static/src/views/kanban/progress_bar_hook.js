// @ts-check
/** @odoo-module native */

/** @module @web/views/kanban/progress_bar_hook - Progress bar state computation, active bar filtering, and per-group aggregate tracking for kanban columns */

import { onWillDestroy, reactive } from "@odoo/owl";
import { Domain } from "@web/core/domain";
import { _t } from "@web/core/l10n/translation";
import { debounce } from "@web/core/utils/timing";
import {
    extractInfoFromGroupData,
    getAggregateSpecifications,
} from "@web/model/relational_model/utils";

/** @import { Group } from "@web/model/relational_model/group" */

const FALSE = Symbol("False");

// Delay (ms) after the last locally reconciled move before a full
// authoritative `read_progress_bar` refresh fires (see _scheduleMoveReconcile).
const MOVE_RECONCILE_DELAY = 300;

/**
 * Find a group entry matching a specific group-by field value.
 * @param {Object[]} groups - Aggregate group data from formatted_read_group.
 * @param {Object} groupByField - Field descriptor with a `name` property.
 * @param {*} value - The group value to match.
 * @returns {Object} The matching group entry, or an empty object.
 */
function _findGroup(groups, groupByField, value) {
    return groups.find((g) => g[groupByField.name] === value) || {};
}

/**
 * Build a domain filter for a selected progress bar segment.
 * @param {string} fieldName - The progress bar field name.
 * @param {Object[]} bars - All bar segments (including the "Other" sentinel).
 * @param {*} value - The selected bar value, or FALSE symbol for "Other".
 * @returns {Array} An Odoo domain expression.
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
 * Convert raw formatted_read_group results into aggregate value maps.
 * @param {Object[]} groups - Raw group data from formatted_read_group.
 * @param {string[]} groupBy - The group-by specification.
 * @param {Object} fields - Field definitions.
 * @param {Array} [domain] - Optional domain used for the read.
 * @returns {Object[]} Array of aggregate value objects keyed by field name.
 */
function _groupsToAggregateValues(groups, groupBy, fields, domain) {
    const groupByFieldName = groupBy[0].split(":")[0];
    return groups.map((g) => {
        const groupInfo = extractInfoFromGroupData(g, groupBy, fields, domain);
        return Object.assign(groupInfo.aggregates, {
            [groupByFieldName]: groupInfo.serverValue,
        });
    });
}

/**
 * Reactive state manager for kanban column progress bars.
 *
 * Tracks per-group bar segment counts, active bar selection (filtering),
 * and aggregate values. Coordinates with the model to load progress bar
 * data via `read_progress_bar` RPC and refresh counts after record changes.
 */
class ProgressBarState {
    /**
     * @param {Object} progressAttributes - Parsed `<progressbar>` arch config.
     * @param {Object} model - The kanban RelationalModel instance.
     * @param {Object[]} aggregateFields - Fields to compute aggregates for.
     * @param {Object} [activeBars={}] - Restored active bar selections keyed by group serverValue.
     */
    constructor(progressAttributes, model, aggregateFields, activeBars = {}) {
        this.progressAttributes = progressAttributes;
        this.model = model;
        this._groupsInfo = {};
        this._aggregateFields = aggregateFields;
        this.activeBars = activeBars;
        this._aggregateValues = [];
        this._pbCounts = null;
        // Stale-response guards for the concurrent refresh RPCs (see updateCounts)
        this._pbEpoch = 0;
        // Epoch for fetches writing `_aggregateValues` (full-domain
        // _updateAggregates and group-scoped _updateAggregatesForGroups).
        // Fetches writing `activeBars[*].aggregates` (_updateAggregateGroup)
        // target per-(group, bar) state instead and use per-group epochs, so
        // the two kinds of fetch never discard each other's responses.
        this._aggEpoch = 0;
        /** @type {Map<*, number>} keyed by group serverValue */
        this._groupAggEpochs = new Map();
        // Deselections in flight (see _deselectEmptyActiveBars), keyed by
        // group serverValue, to avoid firing the same reload twice.
        this._pendingBarDeselections = new Set();
        // Pending drag & drop moves, keyed by record datapoint id (see registerRecordMove)
        this._recordMoves = new Map();
    }

    /**
     * Get or compute progress bar info for a group (bars, active selection, readiness).
     * @param {Group} group - The kanban group datapoint.
     * @returns {{ activeBar: string | null, bars: Object[], isReady: boolean }}
     */
    getGroupInfo(group) {
        if (this._pbCounts === null) {
            // progressbar isn't loaded yet
            return {
                activeBar: null,
                bars: [],
                isReady: false,
            };
        }
        if (!this._groupsInfo[group.id]) {
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
                // Clamp to >= 0: a stale _pbCounts vs. a fresher (smaller)
                // group.count — e.g. mid slow read_progress_bar after a
                // filter toggle — can make the naive remainder negative.
                count: Math.max(
                    0,
                    group.count - bars.map((r) => r.count).reduce((a, b) => a + b, 0),
                ),
                value: /** @type {any} */ (FALSE),
                string: _t("Other"),
                color: "200",
            });

            // Update activeBars count and aggregates. Deselecting an emptied
            // active bar is NOT done here: getGroupInfo runs on render paths,
            // so the applyFilter RPC lives in _deselectEmptyActiveBars
            // (data-update paths) instead.
            if (this.activeBars[group.serverValue]) {
                this.activeBars[group.serverValue].count = bars.find(
                    (x) => x.value === this.activeBars[group.serverValue].value,
                ).count;

                if (this._aggregateFields.length) {
                    // No need to recompute: formatted_read_group already ran
                    // with the correct (filtered) domain.
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
                // Width denominator: sum of bar counts, not live group.count
                // — equal in steady state, but keeps widths coherent while
                // records reload before read_progress_bar resolves (else a
                // stale count over a smaller denominator overflows maxWidth).
                total: bars.reduce((sum, bar) => sum + bar.count, 0),
                isReady: true,
            };

            this._groupsInfo[group.id] = progressBar;
        }
        return this._groupsInfo[group.id];
    }

    /**
     * Compute the displayed aggregate value for a group's progress bar header.
     * @param {Group} group - The kanban group datapoint.
     * @param {Object} aggregateField - The sum field definition.
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
     * Toggle a progress bar segment selection, filtering the group's records.
     * @param {string} groupId - The group datapoint ID.
     * @param {{ value: * }} bar - The bar segment that was clicked.
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
     * Re-fetch aggregate values for a single group after bar selection changes.
     * @param {Group} group - The group to update.
     * @param {Object[]} bars - Current bar segments.
     * @param {Object} activeBar - The active bar selection with `value` and `aggregates`.
     * @returns {Promise<void>}
     */
    async _updateAggregateGroup(group, bars, activeBar) {
        // Per-group stale-response guard: a superseded fetch for the SAME
        // group must not overwrite activeBar.aggregates, but fetches for
        // other groups (or the _aggregateValues fetchers) write different
        // targets and must not discard this one.
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
            return; // a more recent fetch for this group superseded this one
        }
        if (groups.length) {
            const groupByField = group.groupByField;
            const aggrValues = _groupsToAggregateValues(
                groups,
                groupBy,
                fields,
                domain,
            );
            activeBar.aggregates = _findGroup(
                aggrValues,
                groupByField,
                group.serverValue,
            );
        }
    }

    /**
     * Refresh progress bar counts and aggregates after a record change.
     *
     * For a drag & drop between two groups (registered beforehand via
     * `registerRecordMove`), the two affected groups' bars are reconciled
     * locally and aggregates are refetched for those two groups only, instead
     * of firing `read_progress_bar` + `formatted_read_group` over the full
     * domain. Every other change (quick create, edited record, bar
     * (de)selection) still triggers a full refresh.
     *
     * @param {Group} group - The group where the change occurred.
     * @param {Object} [record] - The saved record datapoint, when the change
     *   comes from a record save.
     */
    updateCounts(group, record) {
        const move = record && this._recordMoves.get(record.id);
        if (move) {
            this._recordMoves.delete(record.id);
        }
        if (!(move && this._reconcileMove(record, move))) {
            // Fire-and-forget refreshes: catch to avoid unhandled rejections
            this._updateProgressBar().catch((error) => console.error(error));
            if (this._aggregateFields.length) {
                this._updateAggregates().catch((error) => console.error(error));
                this.updateAggregateGroup(group);
            }
        }

        // If the selected bar is empty, remove the selection. Use a distinct loop
        // variable so it does not shadow the `group` parameter above.
        for (const emptyGroup of this.model.root.groups) {
            if (
                this.activeBars[emptyGroup.serverValue] &&
                emptyGroup.list.count === 0
            ) {
                // Fire-and-forget: selectBar awaits applyFilter RPCs, so
                // catch rejections like the two refreshes above.
                this.selectBar(emptyGroup.id, { value: null }).catch((error) =>
                    console.error(error),
                );
            }
        }
    }

    /**
     * Notify that a record is about to be moved between two groups (drag &
     * drop). The `updateCounts` call triggered by the resulting save will
     * reconcile the two groups locally instead of refetching all counts.
     *
     * @param {string} recordId - The record datapoint id.
     * @param {string} sourceGroupId
     * @param {string} targetGroupId
     */
    registerRecordMove(recordId, sourceGroupId, targetGroupId) {
        if (this._recordMoves.has(recordId)) {
            // A previous move of the same record is still pending (its save
            // hasn't been reconciled yet). Registering the new one would make
            // the first save consume the wrong {source, target, sourceValue}
            // pair; ignoring it makes the second save fall back to a full,
            // authoritative refresh instead.
            return;
        }
        const groups = this.model.root.groups || [];
        const sourceGroup = groups.find((g) => g.id === sourceGroupId);
        const record = sourceGroup?.list.records.find((r) => r.id === recordId);
        this._recordMoves.set(recordId, {
            sourceGroupId,
            targetGroupId,
            // Captured before the save: the source bucket must be decremented
            // by the value the record had while counted in the source group
            // (the save itself may rewrite the progress field server-side).
            sourceValue: record?.data[this.progressAttributes.fieldName],
        });
    }

    /**
     * Drop a pending move registration (no-op if it was already consumed by
     * `updateCounts`). Called when the move failed or was reverted.
     * @param {string} recordId - The record datapoint id.
     */
    cancelRecordMove(recordId) {
        this._recordMoves.delete(recordId);
    }

    /**
     * Locally reconcile the bars after a record was dragged from one group to
     * another: decrement the source group's bucket, increment the target
     * group's, and refetch aggregates for those two groups only (domain
     * scoped to the groups) instead of over the full domain.
     *
     * @param {Object} record - The moved record datapoint (already saved).
     * @param {Object} move - `{ sourceGroupId, targetGroupId, sourceValue }`.
     * @returns {boolean} Whether the move was reconciled locally. When false,
     *   the caller falls back to a full refresh: local reconcile is
     *   impossible (bars not loaded yet, groups reloaded under us, progress
     *   field not part of the fetched fields) or ambiguous (grouped on the
     *   progress field itself, whose old value is unknown).
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
        // Invalidate in-flight full refreshes: their (older) responses must
        // not overwrite the locally reconciled counts.
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
     * Apply a +1/-1 delta to a group's bar bucket for a given progress field
     * value, keeping the `_pbCounts` snapshot, the cached bars, the snapshot
     * ``total`` and the active bar count in sync. The "Other" (FALSE) bar is
     * recomputed as the remainder against the group's live count, as in
     * `_refreshBars`.
     *
     * @param {Group} group
     * @param {*} value - The moved record's progress field value.
     * @param {number} delta - +1 or -1.
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
            // Never rendered (e.g. always-folded group): the snapshot above is
            // enough, getGroupInfo will build the bars from it when needed.
            return;
        }
        if (bucket) {
            const bar = groupInfo.bars.find((b) => b.value === bucket);
            if (bar) {
                bar.count = Math.max(0, bar.count + delta);
            }
        }
        // The "Other" bar absorbs the remainder against the live group count.
        const coloredCount = groupInfo.bars
            .filter((b) => b.value !== FALSE)
            .reduce((sum, b) => sum + b.count, 0);
        groupInfo.bars.find((b) => b.value === FALSE).count = Math.max(
            0,
            group.count - coloredCount,
        );
        groupInfo.total = groupInfo.bars.reduce((sum, bar) => sum + bar.count, 0);
        if (this.activeBars[group.serverValue]) {
            this.activeBars[group.serverValue].count = groupInfo.bars.find(
                (x) => x.value === this.activeBars[group.serverValue].value,
            ).count;
        }
    }

    /**
     * Re-fetch aggregate values for the given groups only, with a domain
     * scoped to those groups, and merge the result into `_aggregateValues`.
     *
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
            return; // a more recent call superseded this one
        }
        const aggrValues = _groupsToAggregateValues(groups, groupBy, fields, domain);
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

    /**
     * Schedule a trailing, authoritative refresh after a burst of locally
     * reconciled moves: one full `read_progress_bar` (and aggregate re-read
     * when relevant) fires once no move has happened for
     * MOVE_RECONCILE_DELAY ms. This bounds the drift a purely local reconcile
     * could accumulate (e.g. concurrent edits from other tabs/users, or
     * server-side writes triggered by the move) to a single burst window.
     */
    _scheduleMoveReconcile() {
        if (!this._moveReconcileDebounced) {
            this._moveReconcileDebounced = debounce(() => {
                this._updateProgressBar().catch((error) => console.error(error));
                if (this._aggregateFields.length) {
                    this._updateAggregates().catch((error) => console.error(error));
                    // _updateAggregates only rewrites _aggregateValues; the
                    // headers of groups with an active bar read
                    // activeBars[*].aggregates, so refresh those too — the
                    // trailing refresh must be authoritative for both.
                    for (const group of this.model.root.groups || []) {
                        this.updateAggregateGroup(group);
                    }
                }
            }, MOVE_RECONCILE_DELAY);
        }
        this._moveReconcileDebounced();
    }

    /**
     * Re-fetch aggregates for a group if it has an active bar selection.
     * @param {Group} group - The group to update.
     */
    updateAggregateGroup(group) {
        if (group && this.activeBars[group.serverValue]) {
            const { bars } = this.getGroupInfo(group);
            // Fire-and-forget refresh: catch to avoid unhandled rejections
            this._updateAggregateGroup(
                group,
                bars,
                this.activeBars[group.serverValue],
            ).catch((error) => console.error(error));
        }
    }

    /** Re-fetch aggregate values for all groups from the server. */
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
            return; // a more recent call superseded this one
        }
        this._aggregateValues = _groupsToAggregateValues(groups, groupBy, fields);
    }

    /** Re-fetch progress bar segment counts for all groups via `read_progress_bar`. */
    async _updateProgressBar() {
        const groupBy = this.model.root.groupBy;
        if (groupBy.length) {
            const epoch = ++this._pbEpoch;
            const resModel = this.model.root.resModel;
            const domain = this.model.root.domain;
            const context = this.model.root.context;
            const { colors, fieldName: field, help } = this.progressAttributes;
            const groupsId = this.model.root.groups.map((g) => g.id).join();
            const res = await this.model.orm.call(resModel, "read_progress_bar", [], {
                domain,
                group_by: groupBy[0],
                progress_bar: { colors, field, help },
                context,
            });
            if (epoch !== this._pbEpoch) {
                return; // a more recent call superseded this one
            }
            if (groupsId !== this.model.root.groups.map((g) => g.id).join()) {
                return;
            }
            this._pbCounts = res;
            this._refreshBars();
        }
    }

    /**
     * Re-sync every visible group's bar counts and snapshot ``total`` from
     * ``_pbCounts``, mutating cached bar objects in place (not discarding
     * ``_groupsInfo``) to preserve object identity and active-bar/filter
     * state — safe to call after a (re)load to fix bars rendered from a
     * half-loaded epoch (only one of read_progress_bar/web_read_group resolved).
     */
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
            // Keep the snapshot denominator in sync with the refreshed counts.
            groupInfo.total = groupInfo.bars.reduce((sum, bar) => sum + bar.count, 0);
            if (this.activeBars[group.serverValue]) {
                this.activeBars[group.serverValue].count = groupInfo.bars.find(
                    (x) => x.value === this.activeBars[group.serverValue].value,
                ).count;
            }
        }
        this._deselectEmptyActiveBars();
    }

    /**
     * Drop active bar selections whose segment count reached 0 (e.g. a
     * restored selection whose records are gone, or a reload that emptied
     * the bar), removing the group filter. Data-update counterpart of the
     * count sync done in ``getGroupInfo``, which runs on render paths and
     * must stay side-effect free.
     */
    _deselectEmptyActiveBars() {
        if (this._pbCounts === null) {
            return;
        }
        for (const group of this.model.root.groups) {
            if (group.isFolded) {
                continue;
            }
            const activeBar = this.activeBars[group.serverValue];
            if (!activeBar || this._pendingBarDeselections.has(group.serverValue)) {
                continue;
            }
            const { bars } = this.getGroupInfo(group);
            const count = bars.find((x) => x.value === activeBar.value)?.count || 0;
            if (count === 0) {
                this._pendingBarDeselections.add(group.serverValue);
                group
                    .applyFilter(undefined)
                    .then(() => {
                        delete this.activeBars[group.serverValue];
                        group.model.notify();
                    })
                    .catch((error) => console.error(error))
                    .finally(() =>
                        this._pendingBarDeselections.delete(group.serverValue),
                    );
            }
        }
    }

    /**
     * Initial load of progress bar data. Called during model root loading.
     * @param {{ context: Object, domain: Array, groupBy: string[], resModel: string }} params
     */
    async loadProgressBar({ context, domain, groupBy, resModel }) {
        if (groupBy.length) {
            // Participate in the _pbEpoch protocol (like _updateProgressBar/
            // _reconcileMove): bump on entry, re-check after the RPC. This
            // fails an in-flight stale _updateProgressBar's epoch check when
            // it resolves after this (re)load, and a stale loadProgressBar
            // can't clobber a fresher one either.
            const epoch = ++this._pbEpoch;
            const { colors, fieldName: field, help } = this.progressAttributes;
            const res = await this.model.orm.call(resModel, "read_progress_bar", [], {
                domain,
                group_by: groupBy[0],
                progress_bar: { colors, field, help },
                context,
            });
            if (epoch !== this._pbEpoch) {
                return; // a more recent progress bar refresh superseded this load
            }
            this._pbCounts = res;
        }
    }

    /**
     * Get the filtered record count for a group with an active bar.
     * @param {Group} group
     * @returns {number | undefined} Count if a bar is active, undefined otherwise.
     */
    getGroupCount(group) {
        const progressBarInfo = this.getGroupInfo(group);
        if (progressBarInfo.activeBar) {
            const progressBar = progressBarInfo.bars.find(
                (b) => b.value === progressBarInfo.activeBar,
            );
            return progressBar.count;
        }
    }

    /**
     * Drop cached per-group progress bar info for groups that no longer exist in
     * the current root (e.g. after a reload with a different filter/groupBy).
     * ``_groupsInfo`` is keyed by datapoint id and lazily filled by
     * ``getGroupInfo``; without pruning, stale entries (and the record lists
     * they retain through closures) would accumulate forever.
     */
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
     * Match groups from read_progress_bar with those from formatted_read_group.
     * Grouped on date(time) fields: displayName of the period (e.g. "W8 2024").
     * Boolean fields: "True"/"False". Falsy (e.g. unset many2one): "False".
     * Otherwise: the group's value (e.g. id for a many2one).
     *
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
 * OWL composition hook that creates and wires a reactive ProgressBarState.
 *
 * Intercepts the model's `onWillLoadRoot` and `onRootLoaded` hooks to
 * trigger parallel progress bar data loading alongside the main data fetch.
 * On first load, the progress bar loads asynchronously (non-blocking) so
 * the kanban view appears as fast as possible.
 *
 * @param {Object} progressAttributes - Parsed `<progressbar>` arch config.
 * @param {Object} model - The kanban RelationalModel instance.
 * @param {Object[]} aggregateFields - Fields to compute aggregates for.
 * @param {Object} [activeBars] - Restored active bar state from a previous session.
 * @returns {ProgressBarState} Reactive progress bar state.
 */
export function useProgressBar(progressAttributes, model, aggregateFields, activeBars) {
    const progressBarState = reactive(
        new ProgressBarState(progressAttributes, model, aggregateFields, activeBars),
    );

    const onWillLoadRoot = model.hooks.lifecycle.onWillLoadRoot;
    let prom;
    model.hooks.lifecycle.onWillLoadRoot = (config) => {
        onWillLoadRoot();
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
            // On reload, groups are loaded; once read_progress_bar also
            // resolves, re-sync bars to the same epoch as the fresh groups —
            // otherwise a render taken mid-way (only one of the two RPCs
            // resolved) leaves stale counts. Skipped on first load so the
            // view paints asap while the progress bar loads async.
            return prom.then(() => progressBarState._refreshBars());
        }
        // First load (non-blocking): once the bars are known, drop restored
        // active bar selections that turn out to be empty — getGroupInfo no
        // longer does this from the render path.
        prom.then(() => progressBarState._deselectEmptyActiveBars()).catch((error) =>
            console.error(error),
        );
    };
    onWillDestroy(() => progressBarState._moveReconcileDebounced?.cancel());

    return progressBarState;
}
