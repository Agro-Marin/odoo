/** @odoo-module native */
import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import {
    buildM2OFieldDescription,
    computeM2OProps,
    extractM2OFieldProps,
    Many2One,
    Many2OneField,
} from "@web/fields/relational/many2one";
import { Many2XAutocomplete } from "@web/fields/relational/many2x_autocomplete";
import { FormViewDialog } from "@web/views/view_dialogs";

class PackageFormDialog extends FormViewDialog {}

class Many2XStockPackageAutocomplete extends Many2XAutocomplete {
    get createDialog() {
        if (!this._createDialog) {
            const self = this;
            this._createDialog = class extends PackageFormDialog {
                static defaultProps = {
                    ...PackageFormDialog.defaultProps,
                    onRecordSave: async (record) => {
                        const saved = await record.save({ reload: true });
                        if (saved && self.props.update) {
                            self.props.update([{ ...record.data, id: record.resId }]);
                        }
                        return saved;
                    },
                };
            };
        }
        return this._createDialog;
    }
}

class StockPackageMany2OneReplacer extends Many2One {
    static components = {
        ...Many2One.components,
        Many2XAutocomplete: Many2XStockPackageAutocomplete,
    };
}

export class StockPackageMany2One extends Component {
    static template = "stock.StockPackageMany2One";
    static components = { Many2One: StockPackageMany2OneReplacer };
    static props = {
        ...Many2OneField.props,
        displaySource: { type: Boolean },
        displayDestination: { type: Boolean },
    };

    get isDone() {
        return ["done", "cancel"].includes(this.props.record?.data?.state);
    }

    get m2oProps() {
        const props = computeM2OProps(this.props);
        return {
            ...props,
            context: {
                ...props.context,
                ...this.displayNameContext,
            },
            value: this.displayValue,
        };
    }

    get isEditing() {
        return this.props.record.isInEdition;
    }

    get displayValue() {
        const displayVal = this.props.record.data[this.props.name];
        if (this.isDone && displayVal?.display_name) {
            return {
                ...displayVal,
                display_name: displayVal.display_name.split(" > ").pop(),
            };
        }
        return displayVal;
    }

    get displayNameContext() {
        return {
            show_src_package: this.props.displaySource,
            show_dest_package: this.props.displayDestination,
            is_done: this.isDone,
        };
    }
}

registry.category("fields").add("package_m2o", {
    ...buildM2OFieldDescription(StockPackageMany2One),
    fieldDependencies: [{ name: "state", type: "selection", optional: true }],
    extractProps(staticInfo, dynamicInfo) {
        const context = dynamicInfo.context;
        return {
            ...extractM2OFieldProps(staticInfo, dynamicInfo),
            displaySource: !!context?.show_src_package,
            displayDestination: !!context?.show_dest_package,
        };
    },
});
