/** @odoo-module native */
import { Component } from "@odoo/owl";

import { useService } from "@web/core/utils/hooks";

import { trace } from "../common/approval_trace.js";

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
        const approver = this.props.activity.approver_id.id;
        try {
            await trace.span("activity", "approved", { approver }, () =>
                this.orm.call("approval.approver", "action_approve", [approver]),
            );
        } catch (error) {
            this.props.onChange();
            throw error;
        }
        this.props.activity.remove();
        this.props.onChange();
    }

    async onClickRefuse() {
        const approver = this.props.activity.approver_id.id;
        let result;
        try {
            result = await trace.span("activity", "refused", { approver }, () =>
                this.orm.call("approval.approver", "action_refuse", [approver]),
            );
        } catch (error) {
            this.props.onChange();
            throw error;
        }
        trace.event("activity", "refuse_answered", {
            approver,
            opens_wizard: Boolean(result),
        });
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
