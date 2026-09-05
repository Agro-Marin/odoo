// @ts-check
/** @odoo-module native */

import { EditorDialog } from "@web/components/editor_dialog/editor_dialog";
import { ExpressionEditor } from "@web/components/expression_editor/expression_editor";
import { evaluateExpr } from "@web/core/py_js/py";
import { _t } from "@web/core/translation";
import { user } from "@web/core/user";

export class ExpressionEditorDialog extends EditorDialog {
    static components = { ...EditorDialog.components, ExpressionEditor };
    static template = "web.ExpressionEditorDialog";
    static props = {
        close: Function,
        resModel: String,
        fields: Object,
        expression: String,
        onConfirm: Function,
    };

    /** @returns {string} */
    get initialValue() {
        return this.props.expression;
    }

    /** @returns {string} */
    get invalidMessage() {
        return _t("Expression is invalid. Please correct it");
    }

    get expressionEditorProps() {
        return {
            resModel: this.props.resModel,
            fields: this.props.fields,
            expression: this.state.value,
            update: (/** @type {string} */ expression) => this.update(expression),
        };
    }

    makeDefaultRecord() {
        const record = {};
        for (const [name, { type }] of Object.entries(this.props.fields)) {
            switch (type) {
                case "integer":
                case "float":
                case "monetary":
                    record[name] = name === "id" ? false : 0;
                    break;
                case "one2many":
                case "many2many":
                    record[name] = [];
                    break;
                default:
                    record[name] = false;
            }
        }
        return record;
    }

    /**
     * @returns {boolean}
     */
    isValueValid() {
        try {
            evaluateExpr(this.state.value, {
                ...user.context,
                ...this.makeDefaultRecord(),
            });
            return true;
        } catch {
            return false;
        }
    }
}
