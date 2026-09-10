/** @odoo-module native */
import { Component, useRef } from "@odoo/owl";
import { usePopover } from "@web/ui/popover";

import { ApprovalButtonPopover } from "./approval_button_popover";

export class ApprovalButton extends Component {
    static template = "approval.ApprovalButton";
    static props = { gate: Object };

    setup() {
        this.popover = usePopover(ApprovalButtonPopover);
        this.rootRef = useRef("root");
    }

    get decisions() {
        return this.props.gate.result.steps.flatMap((step) => step.decisions);
    }

    get isWaiting() {
        return this.props.gate.result.steps.some(
            (step) =>
                step.decisions.filter((decision) => decision.state === "approved")
                    .length < step.minimum,
        );
    }

    toggle() {
        if (this.popover.isOpen) {
            this.popover.close();
        } else {
            this.popover.open(this.rootRef.el, { gate: this.props.gate });
        }
    }
}
