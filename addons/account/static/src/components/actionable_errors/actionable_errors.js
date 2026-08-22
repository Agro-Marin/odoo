/** @odoo-module native */
import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/fields/standard_field_props";

const WARNING_TYPE_ORDER = ["danger", "warning", "info"];

export class ActionableErrors extends Component {
    static props = { errorData: { type: Object } };
    static template = "account.ActionableErrors";

    setup() {
        super.setup();
        this.actionService = useService("action");
        this.orm = useService("orm");
    }

    get errorData() {
        return this.props.errorData;
    }

    async handleOnClick(errorData) {
        if (errorData.action_call) {
            const [model, method, args] = errorData.action_call;
            await this.orm.call(model, method, [args]);
            this.actionService.doAction("soft_reload");
        } else {
            let action = errorData.action;
            if (action?.view_mode) {
                action = {
                    ...action,
                    views: action.view_mode.split(",").map((mode) => [false, mode]),
                };
                delete action.view_mode;
            }
            this.actionService.doAction(action);
        }
    }

    /**
     * @param {Object} error
     * @returns {number}
     */
    getLevelRank(error) {
        const rank = WARNING_TYPE_ORDER.indexOf(error.level || "warning");
        return rank === -1 ? WARNING_TYPE_ORDER.length : rank;
    }

    get sortedActionableErrors() {
        return (
            this.errorData &&
            Object.fromEntries(
                Object.entries(this.errorData).sort(
                    ([, a], [, b]) => this.getLevelRank(a) - this.getLevelRank(b),
                ),
            )
        );
    }
}

export class ActionableErrorsField extends ActionableErrors {
    static props = { ...standardFieldProps };

    get errorData() {
        return this.props.record.data[this.props.name];
    }
}

export const actionableErrorsField = { component: ActionableErrorsField };
registry.category("fields").add("actionable_errors", actionableErrorsField);
