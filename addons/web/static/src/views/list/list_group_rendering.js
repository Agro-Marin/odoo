// @ts-check
/** @odoo-module native */

/** @module @web/views/list/list_group_rendering - Group-row rendering helpers extracted from ListRenderer */

/**
 * Group rendering cohort extracted from ``ListRenderer``.
 *
 * Same prototype-mixin pattern as ``list_styling.js``: methods land on
 * ``ListRenderer.prototype`` so subclasses' ``super.<method>(...)`` keeps
 * resolving to the canonical implementation. Field initializations stay in
 * the renderer's setup; only method bodies move here.
 *
 * Covers group mutation (add/edit/create group), aggregate-column/colspan
 * computation (thin wrappers over ``list_group_layout.js`` utilities),
 * group-pager rendering, group menu config, and click/toggle handling.
 */

import { registry } from "@web/core/registry";

import {
    countRecordsInGroup,
    getAggregateColumns as getAggregateColumnsUtil,
    getGroupNameCellColSpan as getGroupNameCellColSpanUtil,
    getGroupPagerCellColspan as getGroupPagerCellColspanUtil,
} from "./list_group_layout.js";

/**
 * Mixin applied to ``ListRenderer.prototype`` after class declaration.
 */
export const listGroupRenderingMixin = {
    /**
     * Whether the renderer should expose a "+ New group" affordance.
     * Active only when the arch enables ``createGroup``, the list is
     * grouped by a single ``many2one`` field, and that field matches
     * the arch's ``defaultGroupBy`` (so the new group is meaningful in
     * the current grouping context).
     */
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
     * Add a new record inside the given group.  Leaves any in-progress
     * edit first (without abandoning unsaved changes) so the new row
     * doesn't collide with a half-saved sibling.
     *
     * @param {Object} group
     */
    async addInGroup(group) {
        const left = await this.props.list.leaveEditMode({ canAbandon: false });
        if (left) {
            group.addNewRecord({}, this.props.editable === "top");
        }
    },

    /**
     * Open the form view for a group's representative record (the
     * "Edit" affordance in a group's gear menu).
     *
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
     * Props for the group-config-menu component (gear icon next to a
     * group header).  Pulls extension entries from the
     * ``group_config_items`` registry so addons can layer custom
     * actions onto every group.
     *
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
     * Format an aggregate value for a single column in a group's
     * aggregate row.  Thin wrapper that delegates to the
     * ``useListAggregates`` hook (``this.agg``); kept on the prototype
     * so subclass overrides like ``super.formatGroupAggregate(...)``
     * keep resolving here.
     *
     * @param {Object} group
     * @param {Object} column
     */
    formatGroupAggregate(group, column) {
        return this.agg.formatGroupAggregate(group, column);
    },

    /**
     * Depth of the given group in the current group-by hierarchy.
     * Drives indentation classes on the group header.
     *
     * @param {Object} group
     */
    getGroupLevel(group) {
        return this.props.list.groupBy.length - group.list.groupBy.length - 1;
    },

    // -----------------------------------------------------------------
    // Aggregate-column / colspan computations
    //
    // Shape-adapters over the pure utilities in ``list_group_layout.js``,
    // kept as overridable methods because subclasses (``stock``,
    // ``hr_recruitment``) pre-process columns/aggregates before dispatch.
    //
    // Group-header layout the helpers cooperatively render:
    //   TH TH TH TH TH AGG AGG TH AGG AGG TH TH TH
    //   0  1  2  3  4   5   6   7  8   9  10 11 12
    //   [    TH 5    ][TH][TH][TH][TH][TH][ TH 3 ]
    //   [ group name ][ aggregate cells  ][ pager]
    // -----------------------------------------------------------------

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
     * Props for the per-group ``Pager`` component shown when a group
     * has more records than its current limit.  Re-renders the
     * renderer after a load so column widths reflow.
     *
     * @param {Object} group
     */
    getGroupPagerProps(group) {
        const list = group.list;
        // For a single leveled group with a countLimit, we already have the full count.
        const total = list.isGrouped ? list.count : group.count;
        return {
            offset: list.offset,
            limit: list.limit,
            total,
            onUpdate: async ({ offset, limit }) => {
                await list.load({ limit, offset });
                this.render(true);
            },
            withAccessKey: false,
        };
    },

    /**
     * Whether the group should render a pager in its header.  False
     * for folded groups (no rows to paginate) and groups whose entire
     * record set fits within the current limit.
     *
     * @param {Object} group
     */
    showGroupPager(group) {
        return !group.isFolded && group.list.limit < group.list.count;
    },

    /**
     * Whether the group should render the gear/config menu.  Limited
     * to groups grouped by a relational field (many2one/many2many)
     * with a non-falsy value — anonymous "Undefined" groups don't get
     * the menu.
     *
     * @param {Object} group
     */
    showGroupConfigMenu(group) {
        return (
            group.value && ["many2one", "many2many"].includes(group.groupByField.type)
        );
    },

    /**
     * Click handler for the group header.  Leaves any in-progress
     * edit before toggling so the user doesn't lose unsaved input
     * when collapsing a group containing the edited row.
     *
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
     * Toggle a group's folded state.  Plain wrapper kept as a method
     * (not inlined) so subclasses can override the toggle behavior
     * (e.g. ``stock`` can refresh on-screen counts after toggle).
     *
     * @param {Object} group
     */
    toggleGroup(group) {
        group.toggle();
    },

    /**
     * Called by ``ListAggregatesRow`` when the user confirms a new
     * group name in the inline group-create input.  Hides the input
     * regardless of whether a value was supplied so the user can
     * confirm/cancel from the same affordance.
     *
     * @param {string} value
     */
    addNewGroup(value) {
        this.state.showGroupInput = false;
        if (value) {
            this.props.list.createGroup(value);
        }
    },
};
