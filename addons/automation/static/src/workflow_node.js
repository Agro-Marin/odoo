/** @odoo-module native */

import { Component } from "@odoo/owl";

import { nodeClasses, runtimeStateLabel, stepDetail } from "./workflow_graph.js";

export class WorkflowNode extends Component {
    static template = "automation.WorkflowNode";
    static props = {
        node: Object,
        readonly: {
            type: Boolean,
            optional: true,
        },
    };

    get step() {
        return this.props.node.data;
    }

    get classNames() {
        return nodeClasses(this.step);
    }

    get stateLabel() {
        return runtimeStateLabel(this.step.runtime_state);
    }

    get detail() {
        return stepDetail(this.step);
    }

    get typeLabel() {
        return this.step.node_type === "action" ? "" : this.step.node_type;
    }
}
