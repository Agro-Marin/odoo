/** @odoo-module native */
import { Component } from "@odoo/owl";

import { _t } from "@web/core/l10n/translation";
import { evaluateExpr } from "@web/core/py_js/py";
import { floatField, FloatField } from "@web/fields/basic/float/float_field";
import { monetaryField, MonetaryField } from "@web/fields/basic/monetary/monetary_field";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

const fieldRegistry = registry.category("fields");

class StockActionField extends Component {
    static props = {
        ...FloatField.props,
        ...MonetaryField.props,
        actionName: { type: String, optional: false },
        actionContext: { type: String, optional: true },
        disabled: { type: String, optional: true },
    };
    static components = {
        FloatField,
        MonetaryField,
    }
    static template = "stock.actionField";

    setup() {
        super.setup();
        this.actionService = useService("action");
        this.fieldType = this.props.record.fields[this.props.name].type;
    }
    
    extractProps () {
        const keysToRemove = ["actionName", "actionContext", "disabled"];
        return Object.fromEntries(
         Object.entries(this.props).filter(([prop]) => !keysToRemove.includes(prop))
       );
    }

    get disabled() {
         return this.props.disabled ? evaluateExpr(this.props.disabled, this.props.record.evalContext) : false;
    }

    _onClick(ev) {
        ev.stopPropagation();
        ev.preventDefault();

        // Get the action name from props.options
        const actionName = this.props.actionName;
        const actionContext = this.props.actionContext
            ? evaluateExpr(this.props.actionContext, this.props.record.evalContext)
            : {};

        // Use the action service to perform the action
        this.actionService.doAction(actionName, {
            additionalContext: { ...actionContext, ...this.props.record.context },
        });
    }
}

const stockActionField = {
    ...floatField,
    ...monetaryField,
    component: StockActionField,
    supportedOptions: [
        // Spread the de-duped float/monetary options into the flat list; wrapping
        // them in an array (the old form) produced a nested entry that option
        // tooling can't read.
        ...Object.values(
            Object.fromEntries(
                [...floatField.supportedOptions, ...monetaryField.supportedOptions].map(
                    (option) => [option.name, option]
                )
            )
        ),
        {
            label: _t("Action Name"),
            name: "action_name",
            type: "string",
        },
        {
            label: _t("Disabled"),
            name: "disabled",
            type: "string",
            help: _t("Python expression evaluated against the record to disable the field."),
        },
    ],
    extractProps: (...args) => {
        // The field descriptor exposes the ORM type under `type`, not `fieldType`
        // — destructuring the wrong key left both branches below dead, silently
        // dropping the child field's props (currency_field, digits, …).
        const [{ context, type: fieldType, options }] = args;
        const action_props = {
            actionName: options.action_name,
            disabled: options.disabled,
            actionContext: context,
        }
        let props = {...action_props}
        if (fieldType === "monetary") {
            props = { ...action_props, ...monetaryField.extractProps(...args) };
        } else if (fieldType === "float") {
            props = { ...action_props, ...floatField.extractProps(...args) };
        };
        return props;
    },
};

fieldRegistry.add("stock_action_field", stockActionField);
