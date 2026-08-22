// @ts-check
/** @odoo-module native */

import { Component } from "@odoo/owl";
import { useResizable } from "@web/components/resizable_panel/resizable_panel_hook";

export class ResizablePanel extends Component {
    static template = "web.ResizablePanel";

    static props = {
        onResize: { type: Function, optional: true },
        initialWidth: { type: Number, optional: true },
        minWidth: { type: Number, optional: true },
        class: { type: String, optional: true },
        slots: { type: Object },
        handleSide: {
            validate: (val) => ["start", "end"].includes(val),
            optional: true,
        },
    };
    static defaultProps = {
        onResize: () => {},
        initialWidth: 400,
        minWidth: 400,
        class: "",
        handleSide: "end",
    };

    setup() {
        useResizable({
            containerRef: "containerRef",
            handleRef: "handleRef",
            onResize: this.props.onResize,
            getInitialWidth: (props) => props.initialWidth,
            getMinWidth: (props) => props.minWidth,
            getResizeSide: (props) => props.handleSide,
        });
    }

    /**
     * @returns {string}
     */
    get class() {
        const classes = this.props.class.split(" ");
        if (!classes.some((cls) => cls.startsWith("position-"))) {
            classes.push("position-relative");
        }
        return classes.join(" ");
    }
}
