// @ts-check
/** @odoo-module native */

/** @module @web/fields/specialized/ir_ui_view_ace/ace_field - Code editor field variant for ir.ui.view XML arch editing */

/** @odoo-module native */
import { IrUiViewCodeEditor } from "@web/components/ir_ui_view_code_editor/code_editor";
import { registerField } from "@web/fields/_registry";
import { AceField, aceField } from "@web/fields/specialized/ace/ace_field";

// @ts-expect-error OWL static props typing
export class IrUiViewAceField extends AceField {
    static template = "web.IrUIViewAceField";
    static components = { IrUiViewCodeEditor };
}

export const irUiViewAceField = {
    ...aceField,
    component: IrUiViewAceField,
    additionalClasses: ["o_field_ace"],
};

registerField("code_ir_ui_view", irUiViewAceField);
