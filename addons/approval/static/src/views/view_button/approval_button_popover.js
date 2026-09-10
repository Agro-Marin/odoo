/** @odoo-module native */
import { Component } from "@odoo/owl";
import { DateTime } from "luxon";
import { formatDateTime } from "@web/core/l10n/dates";

export class ApprovalButtonPopover extends Component {
    static template = "approval.ApprovalButtonPopover";
    static props = {
        gate: Object,
        close: { type: Function, optional: true },
    };

    get result() {
        return this.props.gate.result;
    }

    get isRefused() {
        return this.result.request?.state === "refused";
    }

    get canAct() {
        return !this.props.gate.syncing && this.props.gate.hasRecord();
    }

    approvedCount(step) {
        return step.decisions.filter((decision) => decision.state === "approved")
            .length;
    }

    formatDate(date) {
        return formatDateTime(
            DateTime.fromSQL(date, { zone: "utc" }).setZone("default"),
        );
    }

    decide(approve, stepId) {
        return this.props.gate.decide(approve, stepId);
    }

    withdraw(approverId, stepId) {
        return this.props.gate.withdraw(approverId, stepId);
    }
}
