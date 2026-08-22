// @ts-check
/** @odoo-module native */

import { Component, useState } from "@odoo/owl";
import { useAction } from "@web/core/action_port";
import { groupBy } from "@web/core/utils/collections/arrays";
import { omit } from "@web/core/utils/collections/objects";
export class ResUserGroupIdsPopover extends Component {
    static template = "web.ResUserGroupIdsPopover";
    static props = {
        close: Function,
        groupId: [Number, Boolean],
        groups: Object,
        privileges: Object,
    };

    /** @type {import("@web/core/action_port").ActionPort} */
    actionService;

    setup() {
        this.actionService = useAction();

        this.state = useState({
            showExtraGroups: false,
        });

        this.groups = this.props.groups;
        this.privileges = this.props.privileges;
        this.group = this.groups[this.props.groupId];
        this.privilege = this.privileges[this.group.privilege_id];

        this.impliedGroups = this.group.impliedByIds
            .map((gid) => this.groups[gid])
            .filter((g) => !this.privilege || g.privilege_id !== this.privilege.id);

        const implyGroups = this.group.implyIds.map((gid) => this.groups[gid]);
        const implyGroupsByPrivilege = groupBy(implyGroups, (g) => g.privilege_id);
        const keysToOmit = this.privilege
            ? ["false", String(this.privilege.id)]
            : ["false"];
        const groupsFromOtherPrivileges = omit(implyGroupsByPrivilege, ...keysToOmit);
        const higherLevelGroups = Object.values(groupsFromOtherPrivileges).map(
            (groups) => groups.at(-1),
        );
        const groupsWithoutPrivilege =
            implyGroupsByPrivilege[/** @type {any} */ (false)] || [];
        const implyGroupsToDisplay = [...groupsWithoutPrivilege, ...higherLevelGroups];
        const { exclusive, joint, extra } = groupBy(implyGroupsToDisplay, (g) => {
            if (g.impliedByIds.length > 1) {
                return g.privilege_id ? "joint" : "extra";
            }
            return "exclusive";
        });
        this.exclusiveImplyGroups = exclusive || [];
        this.jointImplyGroups = joint || [];
        this.jointExtraImplyGroups = extra || [];
    }

    /**
     * @param {Object} group
     * @returns {string}
     */
    getGroupDisplayName(group) {
        const prefix = group.privilege_id
            ? `${this.privileges[group.privilege_id].name}/`
            : "";
        return `${prefix}${group.name}`;
    }

    /** @param {Object} group */
    onGroupClicked(group) {
        this.actionService.doAction({
            res_id: group.id,
            res_model: "res.groups",
            type: "ir.actions.act_window",
            views: [[false, "form"]],
        });
    }
}
