// @ts-check
/** @odoo-module native */

import { Component } from "@odoo/owl";

/**
 * @typedef FlowConnectionClickParams
 * @property {import("./flow_types").FlowConnectionId} connectionId
 * @property {MouseEvent} originalEvent
 */

/**
 * @typedef FlowConnectionProps
 * @property {string} className extra classes a consumer maps onto its own domain
 * @property {import("./geometry/connections").FlowConnectionGeometry} geometry
 * @property {string} label drawn at the connection's midpoint; a domain's own
 *  annotation of the edge, which the editor never authors and never reads
 * @property {(params: FlowConnectionClickParams) => void} onClick
 * @property {boolean} selected
 */

/** @extends {Component<FlowConnectionProps>} */
export class FlowConnection extends Component {
    static template = "web.FlowConnection";
    static defaultProps = {
        className: "",
        label: "",
        onClick: () => {},
        selected: false,
    };
    static props = {
        className: {
            type: String,
            optional: true,
        },
        geometry: {
            type: Object,
        },
        label: {
            type: String,
            optional: true,
        },
        onClick: {
            type: Function,
            optional: true,
        },
        selected: {
            type: Boolean,
            optional: true,
        },
    };

    get classNames() {
        return [
            "o_flow_editor_connection",
            this.props.className,
            this.props.selected ? "o_flow_editor_connection_selected" : "",
        ]
            .filter(Boolean)
            .join(" ");
    }

    /** @param {MouseEvent} ev */
    onClick(ev) {
        ev.stopPropagation();
        this.props.onClick({
            connectionId: this.props.geometry.id,
            originalEvent: ev,
        });
    }
}
