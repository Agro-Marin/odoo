// @ts-check
/** @odoo-module native */

/** @module @web/components/dropzone/dropzone - Visual drop target overlay that tracks drag enter/leave and fires onDrop */

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

    setup() {
        super.setup();
        this.root = useRef("root");
        this.state = useState({
            isDraggingInside: false,
        });
        useEffect(() => this.updatePosition());
        // The overlay is positioned once from the target's bounding rect;
        // follow the target when the page scrolls or resizes mid-drag.
        const throttledUpdatePosition = useThrottleForAnimation(() =>
            this.updatePosition(),
        );
        useExternalListener(document, "scroll", throttledUpdatePosition, {
            capture: true,
        });
        useExternalListener(window, "resize", throttledUpdatePosition);
    }

    updatePosition() {
        // The target may have unmounted (e.g. the host removed the overlay);
        // guard against null elements so we don't throw while tearing down.
        if (!this.props.ref.el || !this.root.el) {
            return;
        }
        const { top, left, width, height } = this.props.ref.el.getBoundingClientRect();
        this.root.el.style.cssText = `top:${top}px;left:${left}px;width:${width}px;height:${height}px;`;
    }
}
