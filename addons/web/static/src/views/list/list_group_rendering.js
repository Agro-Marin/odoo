// @ts-check
/** @odoo-module native */

/** @module @web/views/list/list_group_rendering */

import { registry } from "@web/core/registry";

import {
    countRecordsInGroup,
    getAggregateColumns as getAggregateColumnsUtil,
    getGroupNameCellColSpan as getGroupNameCellColSpanUtil,
    getGroupPagerCellColspan as getGroupPagerCellColspanUtil,
} from "./list_group_layout.js";

export const listGroupRenderingMixin = {
    get canCreateGroup() {
        const { archInfo, list, readonly } = this.props;
        const { activeActions, defaultGroupBy } = archInfo;
        return (
            !readonly &&
            activeActions.createGroup &&
            list.groupByField?.type === "many2one" &&
            list.groupByField.name === defaultGroupBy?.[0]
        );
    },

    /**
     * @param {Object} group
     */
    async addInGroup(group) {
        const left = await this.props.list.leaveEditMode({ canAbandon: false });
        if (left) {
            group.addNewRecord({}, this.props.editable === "top");
        }
    },

    /**
     * @param {Object} group
     */
    editGroupRecord(group) {
        const { resId, resModel } = group.record;
        this.actionService.doAction({
            context: { create: false },
            res_model: resModel,
            res_id: resId,
            type: "ir.actions.act_window",
            views: [[false, "form"]],
        });
    },

    /**
     * @param {Object} group
     * @returns {number}
     */
    nbRecordsInGroup(group) {
        return countRecordsInGroup(group);
    },

    /**
     * @param {Object} group
     */
    getGroupConfigMenuProps(group) {
        return {
            activeActions: this.props.activeActions,
            configItems: registry.category("group_config_items").getEntries(),
            deleteGroup: async () => await this.props.list.deleteGroups([group]),
            dialogClose: this.dialogClose,
            group,
            list: this.props.list,
        };
    },

    /**
     * @param {Object} group
     * @param {Object} column
     */
    formatGroupAggregate(group, column) {
        return this.agg.formatGroupAggregate(group, column);
    },

    /**
     * @param {Object} group
     */
    getGroupLevel(group) {
        return this.props.list.groupBy.length - group.list.groupBy.length - 1;
    },

    getAggregateColumns(group) {
        return getAggregateColumnsUtil(
            /** @type {any} */ (this.columns),
            this.fields,
            group.aggregates,
        );
    },

    getGroupNameCellColSpan(group) {
        return getGroupNameCellColSpanUtil(
            /** @type {any} */ (this.columns),
            this.fields,
            group.aggregates,
            { hasSelectors: this.hasSelectors },
        );
    },

    getGroupPagerCellColspan(group) {
        return getGroupPagerCellColspanUtil(
            /** @type {any} */ (this.columns),
            this.fields,
            group.aggregates,
            { hasOpenFormViewColumn: this.hasOpenFormViewColumn },
        );
    },

    /**
     * @param {Object} group
     */
    getGroupPagerProps(group) {
        const list = group.list;
        const total = list.isGrouped ? list.count : group.count;
        return {
            offset: list.offset,
            limit: list.limit,
            total,
            onUpdate: async ({ offset, limit }) => {
                if (await this.props.list.leaveEditMode()) {
                    await list.load({ limit, offset });
                    this.render(true);
                }
            },
            withAccessKey: false,
        };
    },

    /**
     * @param {Object} group
     */
    showGroupPager(group) {
        return !group.isFolded && group.list.limit < group.list.count;
    },

    /**
     * @param {Object} group
     */
    showGroupConfigMenu(group) {
        return (
            group.value && ["many2one", "many2many"].includes(group.groupByField.type)
        );
    },

    /**
     * @param {PointerEvent} _ev
     * @param {Object} group
     */
    async onGroupHeaderClicked(_ev, group) {
        const left = await this.props.list.leaveEditMode();
        if (left) {
            this.toggleGroup(group);
        }
    },

    /**
     * @param {Object} group
     */
    toggleGroup(group) {
        group.toggle();
    },

    /**
     * @param {string} value
     */
    addNewGroup(value) {
        this.state.showGroupInput = false;
        if (value) {
            this.props.list.createGroup(value);
        }
    },
};
