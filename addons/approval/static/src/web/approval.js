/** @odoo-module native */
import { Component } from "@odoo/owl";

import { useService } from "@web/core/utils/hooks";

/**
 * @typedef {Object} Props
 * @property {import("models").Activity} activity
 * @extends {Component<Props, Env>}
 */
export class Approval extends Component {
    static template = "approval.Approval";
    static props = {
        activity: Object,
        onChange: Function,
    };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
    }

    async onClickApprove() {
        try {
            await this.orm.call("approval.approver", "action_approve", [
                this.props.activity.approver_id.id,
            ]);
        } catch (error) {
            this.props.onChange();
            throw error;
        }
        this.props.activity.remove();
        this.props.onChange();
    }

    async onClickRefuse() {
        let result;
        try {
            result = await this.orm.call("approval.approver", "action_refuse", [
                this.props.activity.approver_id.id,
            ]);
        } catch (error) {
            this.props.onChange();
            throw error;
        }
        if (result) {
            await this.action.doAction(result, {
                onClose: () => this.props.onChange(),
            });
        } else {
            this.props.activity.remove();
            this.props.onChange();
        }
    }
}
