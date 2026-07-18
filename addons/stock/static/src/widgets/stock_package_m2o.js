/** @odoo-module native */
import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { computeM2OProps, Many2One } from "@web/fields/relational/many2one/many2one";
import {
    buildM2OFieldDescription,
    extractM2OFieldProps,
    Many2OneField,
} from "@web/fields/relational/many2one/many2one_field";
import { Many2XAutocomplete } from "@web/fields/relational/many2x_autocomplete";
import { FormViewDialog } from "@web/views/view_dialogs/form_view_dialog";

class PackageFormDialog extends FormViewDialog {}

class Many2XStockPackageAutocomplete extends Many2XAutocomplete {
    get createDialog() {
        // Memoize a per-instance dialog subclass instead of mutating the shared
        // PackageFormDialog.defaultProps on every access — the old form bound
        // onRecordSave to whichever autocomplete last read this getter (last
        // writer wins on a module-level static).
        if (!this._createDialog) {
            const self = this;
            this._createDialog = class extends PackageFormDialog {
                static defaultProps = {
                    ...PackageFormDialog.defaultProps,
                    onRecordSave: async (record) => {
                        // We need to reload to get the name computed from the backend.
                        const saved = await record.save({ reload: true });
                        if (saved && self.props.update) {
                            // Without this, the package is named 'Unnamed' in the UI
                            // until the record is saved.
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
        // NB: relies on `state` being present in the view arch. The widget is
        // used on models both with a `state` field (stock.move.line — whose
        // stock views all declare `<field name="state" column_invisible="True"/>`)
        // and without one (stock.package, stock.quant, stock.quant.relocate),
        // so a widget-level `fieldDependencies` on `state` is NOT an option:
        // it would inject `state` into the read spec of models that don't have
        // the field and crash those views. When adding this widget to a new
        // view on a model with `state`, include the field in the arch.
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
            // Return a trimmed copy; never mutate the record's own datapoint data
            // from a render getter (other consumers/persistence read the same object).
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
    extractProps(staticInfo, dynamicInfo) {
        const context = dynamicInfo.context;
        return {
            ...extractM2OFieldProps(staticInfo, dynamicInfo),
            displaySource: !!context?.show_src_package,
            displayDestination: !!context?.show_dest_package,
        };
    },
});
