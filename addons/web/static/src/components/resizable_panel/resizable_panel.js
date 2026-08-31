// @ts-check
/** @odoo-module native */

import { Component } from "@odoo/owl";
import {
    DEFAULT_PANEL_WIDTH,
    useResizable,
} from "@web/components/resizable_panel/resizable_panel_hook";
import { mergeClasses } from "@web/core/utils/dom/classname";

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
        initialWidth: DEFAULT_PANEL_WIDTH,
        minWidth: DEFAULT_PANEL_WIDTH,
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
     * The panel positions its handle absolutely, so it has to establish a
     * containing block -- unless the caller already chose a `position-*` of
     * their own, which is theirs to keep.
     *
     * @returns {Record<string, boolean>}
     */
    get class() {
        const classes = mergeClasses(this.props.class);
        const positioned = Object.keys(classes).some(
            (cls) => classes[cls] && cls.startsWith("position-"),
        );
        return mergeClasses(classes, { "position-relative": !positioned });
    }
}
