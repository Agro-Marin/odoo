// @ts-check
/** @odoo-module native */

import { Component, onWillDestroy, useEffect, useRef } from "@odoo/owl";
import { mergeClasses } from "@web/core/utils/dom/classname";

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

        id: { type: String, optional: true },
        role: { type: String, optional: true },
        ariaLabel: { type: String, optional: true },
        ariaLabelledBy: { type: String, optional: true },
    };
    static defaultProps = {
        placement: "end",
        class: "",
        role: "dialog",
    };

    /** @type {import("@odoo/owl").Ref<HTMLElement>} */
    panelRef;

    setup() {
        this.panelRef = useRef("panel");

        if (
            odoo.debug &&
            this.props.role &&
            !this.props.ariaLabel &&
            !this.props.ariaLabelledBy
        ) {
            console.warn(
                `[offcanvas] role="${this.props.role}" without an accessible name; ` +
                    `pass ariaLabel or ariaLabelledBy, or role="" to opt out.`,
            );
        }

        useEffect(
            (open) => {
                const el = this.panelRef.el;
                if (!el) {
                    return;
                }
                const wasOpen = el.matches(":popover-open");
                if (open && !wasOpen) {
                    el.showPopover();
                } else if (!open && wasOpen) {
                    el.hidePopover();
                }
                el.classList.toggle("show", open);

                if (open && !wasOpen && !el.contains(document.activeElement)) {
                    el.focus();
                }
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

    /** @returns {Object} */
    get classObj() {
        return mergeClasses(
            `offcanvas offcanvas-${this.props.placement}`,
            this.props.class,
        );
    }
}
