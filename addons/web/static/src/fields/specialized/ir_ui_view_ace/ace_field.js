// @ts-check
/** @odoo-module native */

import { registerField } from "@web/fields/_registry";
import { AceField, aceField } from "@web/fields/specialized/ace/ace_field";
import { IrUiViewCodeEditor } from "@web/fields/specialized/ir_ui_view_ace/ir_ui_view_code_editor";

// @ts-expect-error OWL static props typing
export class IrUiViewAceField extends AceField {
    static template = "web.IrUIViewAceField";
    static components = { IrUiViewCodeEditor };
}

/** @type {import("registries").FieldsRegistryItemShape} */
const irUiViewAceField = {
    ...aceField,
    component: IrUiViewAceField,
    additionalClasses: ["o_field_ace"],
};

registerField("code_ir_ui_view", irUiViewAceField);
