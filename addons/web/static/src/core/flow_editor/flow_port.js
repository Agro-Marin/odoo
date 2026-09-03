// @ts-check
/** @odoo-module native */

import { Component } from "@odoo/owl";

/**
 * @typedef FlowPortPointerDownParams
 * @property {import("./flow_types").FlowNodeId} nodeId
 * @property {import("./flow_types").FlowPort} port
 * @property {PointerEvent} originalEvent
 */

/**
 * @typedef FlowPortProps
 * @property {boolean} connected
 * @property {import("./flow_types").FlowNodeId} nodeId
 * @property {number} offset fraction of the node's height, from its top edge
 * @property {(params: FlowPortPointerDownParams) => void} onPointerDown
 * @property {import("./flow_types").FlowPort} port
 * @property {"valid" | "invalid"} [validation]
 */

/** @extends {Component<FlowPortProps>} */
export class FlowPort extends Component {
    static template = "web.FlowPort";
    static defaultProps = {
        connected: false,
        onPointerDown: () => {},
    };
    static props = {
        connected: {
            type: Boolean,
            optional: true,
        },
        nodeId: {
            type: true,
        },
        offset: {
            type: Number,
        },
        onPointerDown: {
            type: Function,
            optional: true,
        },
        port: {
            type: Object,
        },
        validation: {
            type: String,
            optional: true,
        },
    };

    get style() {
        return `top: ${this.props.offset * 100}%;`;
    }

    /** @param {MouseEvent} ev */
    onClick(ev) {
        ev.stopPropagation();
    }

    /** @param {PointerEvent} ev */
    onPointerDown(ev) {
        ev.stopPropagation();
        this.props.onPointerDown({
            nodeId: this.props.nodeId,
            port: this.props.port,
            originalEvent: ev,
        });
    }
}
