/** @odoo-module native */
import { useAssignUserCommand } from "@mail/views/web/fields/assign_user_command_hook";
import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import {
    buildM2OFieldDescription,
    computeM2OProps,
    extractM2OFieldProps,
    Many2One,
    Many2OneField,
} from "@web/fields/relational/many2one";

import { Avatar } from "../avatar/avatar.js";
import { Many2XAvatarUserAutocomplete } from "../avatar_autocomplete/avatar_many2x_autocomplete.js";

export class Many2OneAvatarUser extends Many2One {
    static components = {
        ...Many2One.components,
        Many2XAutocomplete: Many2XAvatarUserAutocomplete,
    };
}

export class Many2OneAvatarUserField extends Component {
    static template = "mail.Many2OneAvatarUserField";
    static components = { Avatar, Many2OneAvatarUser };
    static props = {
        ...Many2OneField.props,
        withCommand: { type: Boolean },
    };

    setup() {
        if (this.props.withCommand) {
            useAssignUserCommand();
        }
    }

    get m2oProps() {
        return computeM2OProps(this.props);
    }

    get relation() {
        return this.props.record.fields[this.props.name].relation;
    }

    get value() {
        return this.props.record.data[this.props.name];
    }
}

export const many2OneAvatarUserField = {
    ...buildM2OFieldDescription(Many2OneAvatarUserField),
    additionalClasses: ["o_field_many2one_avatar"],
    /**
     * @param {{attrs: Object, options: Object, viewType?: string}} staticInfo
     * @param {Object} dynamicInfo
     * @returns {Object}
     */
    extractProps(staticInfo, dynamicInfo) {
        return {
            ...extractM2OFieldProps(staticInfo, dynamicInfo),
            withCommand: ["form", "list"].includes(staticInfo.viewType),
            canOpen:
                "no_open" in staticInfo.options
                    ? !staticInfo.options.no_open
                    : staticInfo.viewType === "form",
        };
    },
    listViewWidth: [110],
};
registry.category("fields").add("many2one_avatar_user", many2OneAvatarUserField);
