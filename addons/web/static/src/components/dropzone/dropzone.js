// @ts-check
/** @odoo-module native */

/** @module @web/components/dropzone/dropzone */

import { Component, useEffect, useExternalListener, useRef, useState } from "@odoo/owl";
import { useThrottleForAnimation } from "@web/core/utils/timing";

export class Dropzone extends Component {
    static props = {
        extraClass: { type: String, optional: true },
        onDrop: { type: Function, optional: true },
        ref: [Object, Function],
        slots: { type: Object, optional: true },
    };
    static template = "web.Dropzone";

    /** @type {import("@odoo/owl").Ref} */
    root;

    setup() {
        super.setup();
        this.root = useRef("root");
        this.state = useState({
            isDraggingInside: false,
        });
        useEffect(() => this.updatePosition());
        const throttledUpdatePosition = useThrottleForAnimation(() =>
            this.updatePosition(),
        );
        useExternalListener(document, "scroll", throttledUpdatePosition, {
            capture: true,
        });
        useExternalListener(window, "resize", throttledUpdatePosition);
    }

    updatePosition() {
        if (!this.props.ref.el || !this.root.el) {
            return;
        }
        const { top, left, width, height } = this.props.ref.el.getBoundingClientRect();
        // Set the four properties rather than cssText, which would also drop
        // anything else the element was styled with.
        const style = this.root.el.style;
        style.setProperty("top", `${top}px`);
        style.setProperty("left", `${left}px`);
        style.setProperty("width", `${width}px`);
        style.setProperty("height", `${height}px`);
    }
}
