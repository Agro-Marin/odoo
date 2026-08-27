// @ts-check
/** @odoo-module native */

import { _t } from "@web/core/translation";
import { registerField } from "@web/fields/_registry";
import { BooleanField } from "@web/fields/basic/boolean/boolean_field";
import { FieldComponent } from "@web/fields/field_component";
import { SelectionField } from "@web/fields/selection/selection/selection_field";
import { standardFieldProps } from "@web/fields/standard_field_props";
import { usePopover } from "@web/ui/popover/popover_hook";

import { ResUserGroupIdsPopover } from "./res_user_group_ids_popover.js";

class ResUserGroupIdsPrivilegeField extends FieldComponent {
    static template = "web.ResUserGroupIdsPrivilegeField";
    static components = { BooleanField, SelectionField };
    static props = { ...standardFieldProps };

    /** @type {ReturnType<typeof usePopover>} */
    popover;

    setup() {
        this.isDebug = Boolean(odoo.debug);
        this.popover = usePopover(ResUserGroupIdsPopover);
        this.groups = this.env.resUserGroupsInfo.groups;
    }

    /**
     * @returns {number[]}
     */
    get disjointGroupIds() {
        const group = this.group || this.impliedGroup;
        return group ? group.disjointIds : [];
    }

    /**
     * @returns {Object | false}
     */
    get group() {
        const value = this.field.value;
        if (!value) {
            return false;
        }
        const gid =
            this.type === "selection"
                ? value
                : this.env.resUserGroupsInfo.booleanFieldToGroupId[this.props.name];
        return this.groups[gid] || false;
    }

    /**
     * @returns {Object | false}
     */
    get impliedGroup() {
        const groups = this.groups;
        const gid = this.findGroupId((gid) => groups[gid].impliedByIds.length);
        return gid !== false ? groups[gid] || false : false;
    }

    /**
     * @returns {string}
     */
    get impliedGroupDisplayName() {
        return !this.isSet && this.impliedGroup
            ? this.groups[this.impliedGroup.id].name
            : "";
    }

    /**
     * @returns {Record<string, boolean>}
     */
    get infoButtonClassnames() {
        const invisible = !this.isSet && !this.impliedGroup?.id;
        const isDisjoint = this.isDisjoint;
        return {
            o_group_info_button: true,
            invisible,
            btn: true,
            "btn-link": true,
            "py-0": true,
            fa: true,
            "fa-info-circle": !isDisjoint,
            "fa-exclamation-triangle": isDisjoint,
            "link-danger": isDisjoint,
        };
    }

    /**
     * @returns {boolean}
     */
    get isDisjoint() {
        return this.disjointGroupIds.length > 0;
    }

    /**
     * @returns {boolean}
     */
    get isImplied() {
        return !this.isSet && !!this.impliedGroup;
    }

    /**
     * @returns {boolean}
     */
    get isSet() {
        return !!this.field.value;
    }

    /**
     * @returns {"selection" | "boolean"}
     */
    get type() {
        return /** @type {"selection" | "boolean"} */ (this.field.type);
    }

    /**
     * @param {(gid: number) => boolean} predicate
     * @returns {number | false}
     */
    findGroupId(predicate) {
        if (this.type === "selection") {
            const options = this.field.definition.selection;
            const option = options.findLast((o) => o[0] && predicate(o[0]));
            return option ? option[0] : false;
        } else {
            const groupId =
                this.env.resUserGroupsInfo.booleanFieldToGroupId[this.props.name];
            return predicate(groupId) ? groupId : false;
        }
    }

    /**
     * @param {MouseEvent} ev
     */
    onClickInfoButton(ev) {
        if (this.popover.isOpen) {
            this.popover.close();
            return;
        }
        const groupId =
            (this.group && this.group.id) ||
            (this.impliedGroup && this.impliedGroup.id);
        if (!groupId) {
            return;
        }
        this.popover.open(/** @type {HTMLElement} */ (ev.currentTarget), {
            groupId,
            groups: this.env.resUserGroupsInfo.groups,
            privileges: this.env.resUserGroupsInfo.privileges,
        });
    }
}

/** @type {import("registries").FieldsRegistryItemShape} */
const resUserGroupIdsPrivilegeField = {
    component: ResUserGroupIdsPrivilegeField,
    displayName: _t("Privilege"),
    supportedTypes: ["boolean", "selection"],
};

registerField("res_user_group_ids_privilege", resUserGroupIdsPrivilegeField);
