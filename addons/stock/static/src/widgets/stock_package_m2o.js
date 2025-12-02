import { Component } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { registry } from "@web/core/registry";
import { computeM2OProps, Many2One } from "@web/views/fields/many2one/many2one";
import {
    buildM2OFieldDescription,
    extractM2OFieldProps,
    Many2OneField,
} from "@web/views/fields/many2one/many2one_field";
import { Many2XAutocomplete } from "@web/views/fields/relational_utils";
import { FormViewDialog } from "@web/views/view_dialogs/form_view_dialog";

/**
 * Custom FormViewDialog for stock packages that forces reload after save.
 *
 * This is needed because package names are computed server-side from sequences,
 * so we need to reload after creation to display the correct name instead of 'Unnamed'.
 *
 * NOTE: We create a proper subclass instead of mutating FormViewDialog.defaultProps
 * to avoid affecting other Many2one fields globally (which would cause bugs like
 * lot_id values being incorrectly assigned to result_package_id).
 */
class StockPackageFormViewDialog extends FormViewDialog {
    setup() {
        super.setup();
        // Override saveRecord to force reload after save
        const originalSaveRecord = this.viewProps.saveRecord;
        this.viewProps.saveRecord = async (record, params) => {
            // Save with reload to get computed name from backend
            const saved = await record.save({ reload: true });
            if (saved) {
                this.currentResId = record.resId;
                await this.props.onRecordSaved(record);
                await this.onRecordSaved(record, params);
            }
            return saved;
        };
    }
}

class Many2XStockPackageAutocomplete extends Many2XAutocomplete {
    get createDialog() {
        return StockPackageFormViewDialog;
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

    setup() {
        this.orm = useService("orm");
        this.isDone = ["done", "cancel"].includes(this.props.record?.data?.state);
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
            displayVal["display_name"] = displayVal["display_name"].split(" > ").pop();
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
