// @ts-check
/** @odoo-module native */

/** @module @web/views/multi_record_group */

import { registry } from "@web/core/registry";

/**
 * Renderer-level group management shared by the multi-record views. Before
 * this module the list mixin (`list/list_group_rendering.js`) and the kanban
 * renderer/header each carried their own copy of the same decisions: whether a
 * new group may be created from the view, how the group config menu is
 * parameterised, and the delete / toggle / quick-create-group flows.
 *
 * The renderers keep their prototype methods (`canCreateGroup`,
 * `getGroupConfigMenuProps`, `deleteGroup`, `toggleGroup`, ...) as thin
 * delegates into this hook — those methods are the extension surface that
 * downstream views override, so they must not move.
 *
 * @typedef {object} GroupManagementContext
 * @property {() => any} getList the view's root list (DynamicGroupList)
 * @property {() => any} [getArchInfo] arch info carrying `activeActions` and
 *   `defaultGroupBy`; required only by the `canCreateGroup` predicate
 * @property {() => boolean} [isReadonly] blocks group creation when true
 *   (the kanban has no readonly rendering mode and omits it)
 * @property {() => any} [getMenuActiveActions] the `activeActions` object the
 *   group config menu receives (renderer-level, not necessarily the arch's);
 *   required only by `getGroupConfigMenuProps`
 * @property {() => any[]} [getDialogClose] the owning component's dialog-close
 *   registry, passed through to the menu; required only by
 *   `getGroupConfigMenuProps`
 * @property {(group: any) => any[]} [getExtraConfigItems] config items
 *   prepended to the registry-provided ones (the kanban adds "Fold")
 * @property {(group: any) => any} [deleteGroup] how the config menu deletes a
 *   group: defaults to this hook's own `deleteGroup`; a component whose delete
 *   flow runs through an overridable prototype method passes a delegate to it
 * @property {() => void} [onGroupDeleted] called after `deleteGroup` resolves
 */

/**
 * Whether the view allows creating a new group in place: only when the arch
 * opted in, the grouping is a many2one, and the view is grouped by its
 * default groupby (creating a value for any other field would not create a
 * column).
 *
 * @param {GroupManagementContext} ctx
 * @returns {boolean}
 */
function computeCanCreateGroup(ctx) {
    const { activeActions, defaultGroupBy } = ctx.getArchInfo?.() || {
        activeActions: {},
    };
    const list = ctx.getList();
    return (
        !ctx.isReadonly?.() &&
        activeActions.createGroup &&
        list.groupByField?.type === "many2one" &&
        list.groupByField.name === defaultGroupBy?.[0]
    );
}

/**
 * @param {GroupManagementContext} ctx
 * @returns {{
 *   canCreateGroup: () => boolean,
 *   getGroupConfigMenuProps: (group: any) => object,
 *   deleteGroup: (group: any) => Promise<void>,
 *   toggleGroup: (group: any) => any,
 *   createGroup: (value: string) => void,
 * }}
 */
export function useGroupManagement(ctx) {
    const self = {
        canCreateGroup() {
            return computeCanCreateGroup(ctx);
        },

        /**
         * Props for `GroupConfigMenu` (`views/view_components`).
         *
         * @param {any} group
         */
        getGroupConfigMenuProps(group) {
            return {
                activeActions: ctx.getMenuActiveActions?.(),
                configItems: [
                    ...(ctx.getExtraConfigItems?.(group) || []),
                    ...registry.category("group_config_items").getEntries(),
                ],
                deleteGroup: async () =>
                    await (ctx.deleteGroup || self.deleteGroup)(group),
                dialogClose: ctx.getDialogClose?.(),
                group,
                list: ctx.getList(),
            };
        },

        /**
         * @param {any} group
         */
        async deleteGroup(group) {
            await ctx.getList().deleteGroups([group]);
            ctx.onGroupDeleted?.();
        },

        /**
         * @param {any} group
         */
        toggleGroup(group) {
            return group.toggle();
        },

        /**
         * Quick-create-group validation: an empty value is a cancel.
         *
         * @param {string} value
         */
        createGroup(value) {
            if (value) {
                ctx.getList().createGroup(value);
            }
        },
    };
    return self;
}
