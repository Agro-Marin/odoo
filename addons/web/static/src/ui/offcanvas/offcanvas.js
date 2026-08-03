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

        // A named role is the whole point of carrying one; an unnamed
        // `role="dialog"` is announced as "dialog" and nothing else, which is
        // worse than the bare `<div popover>` this replaced. The migration off
        // Bootstrap's data-api dropped `aria-labelledby` from both call sites
        // precisely because the component had nowhere to put it, so the check
        // guards the shape of the API rather than any one caller.
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
                // `togglePopover` would race the UA: the element is already in
                // the requested state whenever a light-dismiss got there first.
                const wasOpen = el.matches(":popover-open");
                if (open && !wasOpen) {
                    el.showPopover();
                } else if (!open && wasOpen) {
                    el.hidePopover();
                }
                el.classList.toggle("show", open);

                // After `.show`, never before: Bootstrap's `.offcanvas` is
                // `visibility: hidden` and `.show` is what lifts it, and a
                // `visibility: hidden` element cannot take focus, so focusing
                // first is a silent no-op.
                //
                // Focus IN only. `popover` does not move focus on show, so a
                // panel announced as `role="dialog"` was otherwise reached only
                // by tabbing to it -- what the move off Bootstrap's focus trap
                // cost. The panel itself rather than its first control, as
                // Bootstrap focused it: that is what `tabindex="-1"` is for,
                // and it cannot pop a virtual keyboard open on the way in.
                //
                // Focus OUT is deliberately NOT reimplemented: Chrome records
                // the previously focused element at `showPopover` and restores
                // it on every dismissal path -- Escape, light dismiss, and the
                // `hidePopover` above -- even when this has since moved focus.
                // Verified in Chrome; our own restore would only fight it.
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

    /** @returns {Object} merged CSS class object for the panel element */
    get classObj() {
        return mergeClasses(
            `offcanvas offcanvas-${this.props.placement}`,
            this.props.class,
        );
    }
}
