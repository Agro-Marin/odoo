// @ts-check
/** @odoo-module native */

import { Component, useState } from "@odoo/owl";
import { ExpressionEditor } from "@web/components/expression_editor/expression_editor";
import { evaluateExpr } from "@web/core/py_js/py";
import { _t } from "@web/core/translation";
import { user } from "@web/core/user";
import { useService } from "@web/core/utils/hooks";
import { useConfirmButton } from "@web/ui/dialog/confirm_button_hook";
import { Dialog } from "@web/ui/dialog/dialog";

export class ExpressionEditorDialog extends Component {
    static components = { Dialog, ExpressionEditor };
    static template = "web.ExpressionEditorDialog";
    static props = {
        close: Function,
        resModel: String,
        fields: Object,
        expression: String,
        onConfirm: Function,
    };

    /** @type {(disabled: boolean) => void} */
    setConfirmDisabled;
    /** @type {import("services").ServiceFactories["notification"]} */
    notification;
    /** @type {{ expression: any }} */
    state;

    setup() {
        this.notification = useService("notification");
        this.state = useState({
            expression: this.props.expression,
        });
        this.setConfirmDisabled = useConfirmButton();
    }

    get expressionEditorProps() {
        return {
            resModel: this.props.resModel,
            fields: this.props.fields,
            expression: this.state.expression,
            update: (expression) => {
                this.state.expression = expression;
            },
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
     * One check, and it is local: an expression is valid if it evaluates against a
     * record of the right shape. No server round trip, unlike the domain dialog -
     * which is why this one is not async and the two confirm paths are not shared.
     * @returns {boolean}
     */
    isExpressionValid() {
        try {
            evaluateExpr(this.state.expression, {
                ...user.context,
                ...this.makeDefaultRecord(),
            });
            return true;
        } catch {
            return false;
        }
    }

    onConfirm() {
        this.setConfirmDisabled(true);
        if (!this.isExpressionValid()) {
            this.setConfirmDisabled(false);
            this.notification.add(_t("Expression is invalid. Please correct it"), {
                type: "danger",
            });
            return;
        }
        this.props.onConfirm(this.state.expression);
        this.props.close();
    }

    onDiscard() {
        this.props.close();
    }
}
