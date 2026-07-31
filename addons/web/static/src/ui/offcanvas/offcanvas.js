// @ts-check
/** @odoo-module native */

/** @module @web/ui/offcanvas/offcanvas - Edge-anchored panel built on the native popover attribute */

import { Component, onWillDestroy, useEffect, useRef } from "@odoo/owl";
import { mergeClasses } from "@web/core/utils/dom/classname";

/**
 * Slide-in panel replacing Bootstrap's `data-bs-toggle="offcanvas"`.
 *
 * The panel is a native `popover`, which is what supplies the top layer, the
 * `::backdrop`, Escape and light-dismiss — all of it behaviour Bootstrap
 * reimplements in JS over a z-index stack and a manually inserted backdrop
 * element. Bootstrap's `.offcanvas*` classes are kept for the geometry and the
 * slide transition, which are pure CSS.
 *
 * `open` stays owned by the caller. Escape and light-dismiss are dismissals the
 * component cannot veto, so they are reported through `onClose` rather than
 * silently desynchronising that boolean.
 */
export class Offcanvas extends Component {
    static template = "web.Offcanvas";
    static props = {
        slots: { type: Object },
        open: { type: Boolean },
        onClose: { type: Function, optional: true },
        placement: {
            type: String,
            optional: true,
            validate: (/** @type {string} */ p) =>
                ["start", "end", "top", "bottom"].includes(p),
        },
        class: { optional: true },
    };
    static defaultProps = {
        placement: "end",
        class: "",
    };

    /** @type {import("@odoo/owl").Ref<HTMLElement>} */
    panelRef;

    setup() {
        this.panelRef = useRef("panel");

        useEffect(
            (open) => {
                const el = this.panelRef.el;
                if (!el) {
                    return;
                }
                // `togglePopover` would race the UA: the element is already in
                // the requested state whenever a light-dismiss got there first.
                if (open && !el.matches(":popover-open")) {
                    el.showPopover();
                } else if (!open && el.matches(":popover-open")) {
                    el.hidePopover();
                }
                el.classList.toggle("show", open);
            },
            () => [this.props.open],
        );

        const onToggle = (/** @type {any} */ ev) => {
            if (ev.newState === "closed" && this.props.open) {
                this.props.onClose?.();
            }
        };
        useEffect(
            () => {
                const el = this.panelRef.el;
                el?.addEventListener("toggle", onToggle);
                return () => el?.removeEventListener("toggle", onToggle);
            },
            () => [],
        );
        onWillDestroy(() => {
            const el = this.panelRef.el;
            if (el?.matches(":popover-open")) {
                el.hidePopover();
            }
        });
    }

    /** @returns {Object} merged CSS class object for the panel element */
    get classObj() {
        return mergeClasses(
            `offcanvas offcanvas-${this.props.placement}`,
            this.props.class,
        );
    }
}
