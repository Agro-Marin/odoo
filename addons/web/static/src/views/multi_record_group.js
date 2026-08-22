// @ts-check
/** @odoo-module native */

import { registry } from "@web/core/registry";

/**
 * @typedef {object} GroupManagementContext
 * @property {() => any} getList
 * @property {() => any} [getArchInfo]
 * @property {() => boolean} [isReadonly]
 * @property {() => any} [getMenuActiveActions]
 * @property {() => any[]} [getDialogClose]
 * @property {(group: any) => any[]} [getExtraConfigItems]
 * @property {(group: any) => any} [deleteGroup]
 * @property {() => void} [onGroupDeleted]
 */

/**
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
 * canCreateGroup: () => boolean,
 * getGroupConfigMenuProps: (group: any) => {
 * activeActions: any,
 * configItems: any[],
 * deleteGroup: () => Promise<void>,
 * dialogClose: any,
 * group: any,
 * list: any,
 * },
 * deleteGroup: (group: any) => Promise<void>,
 * toggleGroup: (group: any) => any,
 * createGroup: (value: string) => void,
 * }}
 */
export function useGroupManagement(ctx) {
    const self = {
        canCreateGroup() {
            return computeCanCreateGroup(ctx);
        },

        /**
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
