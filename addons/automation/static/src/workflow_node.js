/** @odoo-module native */

import { Component } from "@odoo/owl";

import { nodeClasses, runtimeStateLabel } from "./workflow_graph.js";

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

    get typeLabel() {
        return this.step.node_type === "action" ? "" : this.step.node_type;
    }
}
