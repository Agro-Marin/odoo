// @ts-check
/** @odoo-module native */

import { Component, useRef, useState } from "@odoo/owl";
import { useLayoutEffect } from "@web/core/utils/layout_effect";
import { useListener } from "@web/core/utils/owl_bridge";
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
        this.root = useRef("root");
        this.state = useState({
            isDraggingInside: false,
        });
        useLayoutEffect(
            () => this.updatePosition(),
            () => [this.props.ref.el, this.root.el],
        );
        const throttledUpdatePosition = useThrottleForAnimation(() =>
            this.updatePosition(),
        );
        useListener(document, "scroll", throttledUpdatePosition, {
            capture: true,
        });
        useListener(window, "resize", throttledUpdatePosition);
    }

    updatePosition() {
        if (!this.props.ref.el || !this.root.el) {
            return;
        }
        const { top, left, width, height } = this.props.ref.el.getBoundingClientRect();
        const style = this.root.el.style;
        style.setProperty("top", `${top}px`);
        style.setProperty("left", `${left}px`);
        style.setProperty("width", `${width}px`);
        style.setProperty("height", `${height}px`);
    }
}
