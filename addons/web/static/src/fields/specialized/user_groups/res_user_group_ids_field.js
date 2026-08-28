// @ts-check
/** @odoo-module native */

import { onWillRender, toRaw, useChildSubEnv } from "@odoo/owl";
import { x2ManyCommands } from "@web/core/network/commands";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { deepCopy } from "@web/core/utils/collections/objects";
import { parseXML } from "@web/core/utils/dom/xml";
import { escape } from "@web/core/utils/format/strings";
import { registerField } from "@web/fields/_registry";
import { FieldComponent } from "@web/fields/field_component";
import { standardFieldProps } from "@web/fields/standard_field_props";
import { Record } from "@web/model/record";

const viewRegistry = registry.category("views");

class ResUserGroupIdsField extends FieldComponent {
    static template = "web.ResUserGroupIdsField";
    static get components() {
        return { Record, FormRenderer: viewRegistry.get("form").Renderer };
    }
    static props = { ...standardFieldProps };

    setup() {
        const { groups, privileges, categories } = deepCopy(
            toRaw(this.props.record.data.view_group_hierarchy),
        );
        this.hierarchyGroups = groups;
        this.categories = this.buildCategories(categories, privileges);
        this.extraCategory = this.buildExtraCategory(groups);

        const booleanFieldToGroupId = this.buildFields(privileges, groups);
        this.fields = deepCopy(this._fields);
        this.archInfo = this.buildArch();

        this.info = { booleanFieldToGroupId, groups: {}, privileges };
        useChildSubEnv({ resUserGroupsInfo: this.info });
        onWillRender(() => this.updateRenderState());

        this.hooks = {
            lifecycle: {
                onRecordChanged: this.onRecordChanged.bind(this),
            },
        };
    }

    /**
     * @param {Array<{ id: string|number, name: string, privilege_ids: Array<string|number> }>} categories
     * @param {Object<string, any>} privileges
     * @returns {Array<Object<string, any>>}
     */
    buildCategories(categories, privileges) {
        const orphans = Object.values(privileges)
            .filter((privilege) => !privilege.category_id)
            .sort((p1, p2) => p1.sequence - p2.sequence);
        if (orphans.length) {
            categories.push({
                id: "other",
                name: _t("Other"),
                privilege_ids: orphans.map((privilege) => privilege.id),
            });
        }
        return categories;
    }

    /**
     * @param {Object<string, any>} groups
     * @returns {{ id: string, name: string, privileges: Array<Object<string, any>> }}
     */
    buildExtraCategory(groups) {
        return {
            id: "extra",
            name: _t("Extra Rights"),
            privileges: Object.values(groups)
                .filter((group) => !group.privilege_id)
                .map((group) => {
                    const privilege = {
                        description: group.comment,
                        groupId: group.id,
                        id: `group_${group.id}`,
                        name: group.name,
                    };
                    privilege.groupFieldName = this.getFieldName(privilege);
                    return privilege;
                })
                .sort((p1, p2) => p1.name.localeCompare(p2.name)),
        };
    }

    /**
     * @param {Object<string, any>} privileges
     * @param {Object<string, any>} groups
     * @returns {Object<string, number>}
     */
    buildFields(privileges, groups) {
        this._fields = {};
        const booleanFieldToGroupId = {};
        for (const category of this.categories) {
            category.privileges = [];
            for (const privilegeId of category.privilege_ids) {
                const privilege = privileges[privilegeId];
                category.privileges.push(privilege);
                this._fields[this.getFieldName(privilege)] = {
                    help: this.getPrivilegeHelp(privilege, groups),
                    selection: this.getPrivilegeSelection(privilege, groups),
                    string: privilege.name,
                    type: "selection",
                };
            }
        }
        for (const privilege of this.extraCategory.privileges) {
            this._fields[privilege.groupFieldName] = {
                help: privilege.description,
                string: privilege.name,
                type: "boolean",
            };
            booleanFieldToGroupId[privilege.groupFieldName] = privilege.groupId;
        }
        return booleanFieldToGroupId;
    }

    /**
     * @param {Object<string, any>} privilege
     * @param {Object<string, any>} groups
     * @returns {string}
     */
    getPrivilegeHelp(privilege, groups) {
        const lines = privilege.description ? [privilege.description] : [];
        for (const gid of privilege.group_ids) {
            if (groups[gid].comment) {
                lines.push(`- ${groups[gid].name}: ${groups[gid].comment}`);
            }
        }
        return lines.join("\n");
    }

    /**
     * @param {Object<string, any>} privilege
     * @param {Object<string, any>} groups
     * @returns {Array<[number|false, string]>}
     */
    getPrivilegeSelection(privilege, groups) {
        const selection = privilege.group_ids.map((gId) => [gId, groups[gId].name]);
        selection.unshift([false, privilege.placeholder || ""]);
        return selection;
    }

    /**
     * @returns {Object<string, any>}
     */
    buildArch() {
        const arch = `
            <t>
                <group>
                    ${this.categories.map((category) => this.getCategoryArch(category)).join("")}
                </group>
                ${odoo.debug ? this.getExtraGroupsArch() : ""}
            </t>`;
        const { ArchParser } = viewRegistry.get("form");
        return new ArchParser().parse(
            parseXML(arch),
            { main: { fields: this._fields } },
            "main",
        );
    }

    updateRenderState() {
        const selectedIds = new Set(this.field.value.currentIds);
        this.updateGroupStates(selectedIds);
        this.updateDisjointIds();
        this.updateReachableSelections();
        this.updateValues(selectedIds);
    }

    /**
     * @param {Set<number>} selectedIds
     */
    updateGroupStates(selectedIds) {
        for (const group of Object.values(this.hierarchyGroups)) {
            const selected = selectedIds.has(group.id);
            this.info.groups[group.id] = {
                name: group.name,
                id: group.id,
                privilege_id: group.privilege_id,
                comment: group.comment,
                impliedByIds: group.all_implied_by_ids.filter(
                    (gid) => gid !== group.id && selectedIds.has(gid),
                ),
                implyIds: selected
                    ? group.all_implied_ids.filter((gid) => gid !== group.id)
                    : [],
                selected,
            };
        }
    }

    updateDisjointIds() {
        for (const group of Object.values(this.hierarchyGroups)) {
            const { selected, impliedByIds } = this.info.groups[group.id];
            this.info.groups[group.id].disjointIds =
                selected || impliedByIds.length
                    ? group.disjoint_ids.filter(
                          (gid) =>
                              this.info.groups[gid].selected ||
                              this.info.groups[gid].impliedByIds.length,
                      )
                    : [];
        }
    }

    updateReachableSelections() {
        for (const fieldName of Object.keys(this.fields)) {
            if (this.fields[fieldName].type !== "selection") {
                continue;
            }
            const options = this._fields[fieldName].selection;
            this.fields[fieldName].selection = options;
            for (let i = options.length - 1; i > 0; i--) {
                const group = this.info.groups[options[i][0]];
                const isImplied = group.impliedByIds.some(
                    (gid) => this.info.groups[gid].privilege_id !== group.privilege_id,
                );
                if (isImplied) {
                    this.fields[fieldName].selection = options.slice(i);
                    break;
                }
            }
        }
    }

    /**
     * @param {Set<number>} selectedIds
     */
    updateValues(selectedIds) {
        this.values = {};
        this.shadowedGroupIds = [];
        for (const category of this.categories) {
            for (const privilege of category.privileges) {
                let groupId =
                    privilege.group_ids.findLast((gId) => selectedIds.has(gId)) ||
                    false;
                const fieldName = this.getFieldName(privilege);
                const options = this.fields[fieldName].selection;
                if (groupId && !options.some((option) => option[0] === groupId)) {
                    this.shadowedGroupIds.push(groupId);
                    groupId = false;
                }
                this.values[fieldName] = groupId;
            }
        }
        for (const privilege of this.extraCategory.privileges) {
            this.values[this.getFieldName(privilege)] = selectedIds.has(
                privilege.groupId,
            );
        }
    }

    /**
     * @returns {string}
     */
    getExtraGroupsArch() {
        return `
            <group string="${escape(this.extraCategory.name)}" class="o_extra_rights_group">
                <group>
                    ${this.extraCategory.privileges
                        .filter((cat, index) => index % 2 === 0)
                        .map((privilege) => this.getPrivilegeArch(privilege))
                        .join("")}
                </group>
                <group>
                    ${this.extraCategory.privileges
                        .filter((cat, index) => index % 2 === 1)
                        .map((privilege) => this.getPrivilegeArch(privilege))
                        .join("")}
                </group>
            </group>`;
    }

    /**
     * @param {{ id: string | number }} privilege
     * @returns {string}
     */
    getFieldName(privilege) {
        return `field_${privilege.id}`;
    }

    /**
     * @param {{ id: string | number }} privilege
     * @returns {string}
     */
    getPrivilegeArch(privilege) {
        const fieldName = this.getFieldName(privilege);
        return `<field name="${escape(fieldName)}" widget="res_user_group_ids_privilege"/>`;
    }

    /**
     * @param {{ name: string, privileges: Array<{ id: string | number }> }} category
     * @returns {string}
     */
    getCategoryArch(category) {
        return `
            <group string="${escape(category.name)}">
                ${category.privileges.map((privilege) => this.getPrivilegeArch(privilege)).join("")}
            </group>`;
    }

    /**
     * @param {unknown} _
     * @param {{[key: string]: number | boolean}} values
     * @returns {Promise<void>}
     */
    onRecordChanged(_, values) {
        let selectedGroupIds = Object.entries(values)
            .filter(
                ([fieldName, gid]) =>
                    this.fields[fieldName].type === "selection" && gid,
            )
            .map(([_, gid]) => gid);
        const { groups, privileges } = this.info;
        const shadowedGroupIds = this.shadowedGroupIds.filter(
            (gid) => !values[this.getFieldName(privileges[groups[gid].privilege_id])],
        );
        selectedGroupIds = [...selectedGroupIds, ...shadowedGroupIds];
        for (const privilege of this.extraCategory.privileges) {
            if (values[privilege.groupFieldName]) {
                selectedGroupIds.push(privilege.groupId);
            }
        }
        return this.field.update([x2ManyCommands.set(selectedGroupIds)]);
    }
}

/** @type {import("registries").FieldsRegistryItemShape} */
const resUserGroupIdsField = {
    component: ResUserGroupIdsField,
    displayName: _t("User Groups"),
    fieldDependencies: [{ name: "view_group_hierarchy", type: "json", readonly: true }],
    additionalClasses: ["w-100"],
    supportedTypes: ["many2many"],
};

registerField("res_user_group_ids", resUserGroupIdsField);
