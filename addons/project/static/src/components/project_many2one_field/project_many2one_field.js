/** @odoo-module native */
import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import {
    buildM2OFieldDescription,
    computeM2OProps,
    Many2One,
    Many2OneField,
} from "@web/fields/relational/many2one";

export class ProjectMany2OneField extends Component {
    static template = "project.ProjectMany2OneField";
    static components = { Many2One };
    static props = { ...Many2OneField.props };

    get m2oProps() {
        const props = computeM2OProps(this.props);
        const { name, record } = this.props;
        props.cssClass = "w-100";
        if (!record.data[name] && !record._isRequired(name)) {
            props.placeholder = _t("Private");
            props.cssClass += " private_placeholder";
        }
        return props;
    }
}

registry.category("fields").add("project", {
    ...buildM2OFieldDescription(ProjectMany2OneField),
});
