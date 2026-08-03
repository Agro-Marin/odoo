// @ts-check
/** @odoo-module native */

/** @module @web/fields/specialized/user_groups/res_user_group_ids_field */

import { Component, onWillRender, toRaw, useChildSubEnv } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { deepCopy } from "@web/core/utils/collections/objects";
import { parseXML } from "@web/core/utils/dom/xml";
import { escape } from "@web/core/utils/format/strings";
import { registerField } from "@web/fields/_registry";
import { standardFieldProps } from "@web/fields/standard_field_props";
import { Record } from "@web/model/record";
import { x2ManyCommands } from "@web/model/relational_model/commands";

const viewRegistry = registry.category("views");

class ResUserGroupIdsField extends Component {
    static template = "web.ResUserGroupIdsField";
    static get components() {
        return { Record, FormRenderer: viewRegistry.get("form").Renderer };
    }
    static props = { ...standardFieldProps };

    setup() {
        const { groups, privileges, categories } = deepCopy(
            toRaw(this.props.record.data.view_group_hierarchy),
        );

        const privilegesWithoutCategory = Object.values(privileges)
            .filter((privilege) => !privilege.category_id)
            .sort((p1, p2) => p1.sequence - p2.sequence);
        if (privilegesWithoutCategory.length) {
            categories.push({
                id: "other",
                name: _t("Other"),
                privilege_ids: privilegesWithoutCategory.map(
                    (privilege) => privilege.id,
                ),
            });
        }

        this.extraCategory = {
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

        this._fields = {};
        const booleanFieldToGroupId = {};
        for (const category of categories) {
            category.privileges = [];
            for (const privilegeId of category.privilege_ids) {
                const privilege = privileges[privilegeId];
                category.privileges.push(privilege);
                const helpLines = privilege.description ? [privilege.description] : [];
                for (const gid of privilege.group_ids) {
                    if (groups[gid].comment) {
                        helpLines.push(`- ${groups[gid].name}: ${groups[gid].comment}`);
                    }
                }
                const selection = privilege.group_ids.map((gId) => [
                    gId,
                    groups[gId].name,
                ]);
                selection.unshift([false, privilege.placeholder || ""]);
                this._fields[this.getFieldName(privilege)] = {
                    help: helpLines.join("\n"),
                    selection,
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
        this.fields = deepCopy(this._fields);

        const models = { main: { fields: this._fields } };
        const arch = `
            <t>
                <group>
                    ${categories.map((category) => this.getCategoryArch(category)).join("")}
                </group>
                ${odoo.debug ? this.getExtraGroupsArch() : ""}
            </t>`;
        const { ArchParser } = viewRegistry.get("form");
        this.archInfo = new ArchParser().parse(parseXML(arch), models, "main");

        this.info = {
            booleanFieldToGroupId,
            groups: {},
            privileges,
        };
        useChildSubEnv({
            resUserGroupsInfo: this.info,
        });
        onWillRender(() => {
            const selectedIds = new Set(
                this.props.record.data[this.props.name].currentIds,
            );
            for (const group of Object.values(groups)) {
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
            for (const group of Object.values(groups)) {
                let disjointIds = [];
                const { selected, impliedByIds } = this.info.groups[group.id];
                if (selected || impliedByIds.length) {
                    disjointIds = group.disjoint_ids.filter(
                        (gid) =>
                            this.info.groups[gid].selected ||
                            this.info.groups[gid].impliedByIds.length,
                    );
                }
                this.info.groups[group.id].disjointIds = disjointIds;
            }

            for (const fieldName of Object.keys(this.fields)) {
                if (this.fields[fieldName].type === "selection") {
                    const options = this._fields[fieldName].selection;
                    this.fields[fieldName].selection = options;
                    for (let i = options.length - 1; i > 0; i--) {
                        const group = this.info.groups[options[i][0]];
                        const isImplied = group.impliedByIds.some(
                            (gid) =>
                                this.info.groups[gid].privilege_id !==
                                group.privilege_id,
                        );
                        if (isImplied) {
                            this.fields[fieldName].selection = options.slice(i);
                            break;
                        }
                    }
                }
            }

            this.values = {};
            this.shadowedGroupIds = [];
            for (const category of categories) {
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
            if (this.extraCategory) {
                for (const privilege of this.extraCategory.privileges) {
                    this.values[this.getFieldName(privilege)] = selectedIds.has(
                        privilege.groupId,
                    );
                }
            }
        });

        this.hooks = {
            lifecycle: {
                onRecordChanged: this.onRecordChanged.bind(this),
            },
        };
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
        return this.props.record.update({
            [this.props.name]: [x2ManyCommands.set(selectedGroupIds)],
        });
    }
}

/** @type {import("registries").FieldsRegistryItemShape} */
const resUserGroupIdsField = {
    component: ResUserGroupIdsField,
    fieldDependencies: [{ name: "view_group_hierarchy", type: "json", readonly: true }],
    additionalClasses: ["w-100"],
    supportedTypes: ["many2many"],
};

registerField("res_user_group_ids", resUserGroupIdsField);
