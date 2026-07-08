// @ts-check
/** @odoo-module native */

/** @module @web/components/dropzone/dropzone - Visual drop target overlay that tracks drag enter/leave and fires onDrop */

import { Component, useEffect, useRef, useState } from "@odoo/owl";

export class Dropzone extends Component {
    static props = {
        extraClass: { type: String, optional: true },
        onDrop: { type: Function, optional: true },
        ref: [Object, Function],
        slots: { type: Object, optional: true },
    };
    static template = "web.Dropzone";

    setup() {
        super.setup();
        this.root = useRef("root");
        this.state = useState({
            isDraggingInside: false,
        });
        useEffect(() => {
            // The target may have unmounted before this effect runs (e.g. the
            // host removed the overlay); guard against a null ref element so we
            // don't throw while tearing down.
            if (!this.props.ref.el) {
                return;
            }
            const { top, left, width, height } =
                this.props.ref.el.getBoundingClientRect();
            this.root.el.style.cssText = `top:${top}px;left:${left}px;width:${width}px;height:${height}px;`;
        });
    }
}
