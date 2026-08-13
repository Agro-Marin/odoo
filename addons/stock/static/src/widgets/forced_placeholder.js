/** @odoo-module native */
import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import {
    buildM2OFieldDescription,
    computeM2OProps,
    Many2One,
    Many2OneField,
} from "@web/fields/relational/many2one";

export class ForcedPlaceholder extends Many2One {
    static template = "stock.ForcedPlaceholder";
    static components = { ...Many2One.components };
    static props = { ...Many2One.props };
}

export class ForcedPlaceholderField extends Component {
    static template = "stock.ForcedPlaceholderField";
    static components = { ForcedPlaceholder };
    static props = { ...Many2OneField.props };

    get m2oProps() {
        const props = computeM2OProps(this.props);
        return {
            ...props,
            canOpen: !props.readonly && props.canOpen,
        };
    }
}

registry.category("fields").add("stock.forced_placeholder", {
    ...buildM2OFieldDescription(ForcedPlaceholderField),
});
