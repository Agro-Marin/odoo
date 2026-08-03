// @ts-check
/** @odoo-module native */

/** @module @web/ui/collapse/collapse - Height-animated collapsible region driven by an `open` prop */

import { Component, onWillDestroy, useEffect, useRef } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { mergeClasses } from "@web/core/utils/dom/classname";

/**
 * Collapsible region, replacing Bootstrap's `data-bs-toggle="collapse"`.
 *
 * The toggle stays at the call site and owns the boolean. Bootstrap's data-api
 * instead pairs a control to its target by selector, which forces every call
 * site to mint a document-unique id — unworkable inside a `t-foreach`, where
 * the id has to be interpolated from a record id to stay unique.
 *
 * Bootstrap's `.collapse` / `.collapsing` / `.show` classes are kept: only the
 * JS is being retired, the design system still styles against those names, and
 * `.collapsing` is what supplies `overflow: hidden` during the animation.
 */
export class Collapse extends Component {
    static template = "web.Collapse";
    static animationTime = 350;
    static props = {
        slots: { type: Object },
        open: { type: Boolean },
        horizontal: { type: Boolean, optional: true },
        class: { optional: true },
    };
    static defaultProps = {
        horizontal: false,
        class: "",
    };

    /** @type {import("@odoo/owl").Ref<HTMLElement>} */
    contentRef;
    /** @type {Animation | null} */
    animation = null;
    /** False until the first effect pass, so a region that starts open does
     *  not play an opening animation on mount. */
    hasRendered = false;

    setup() {
        this.contentRef = useRef("content");

        useEffect(
            (open) => {
                this.setOpen(open, this.hasRendered);
                this.hasRendered = true;
            },
            () => [this.props.open],
        );
        onWillDestroy(() => this.animation?.cancel());
    }

    /**
     * Only the caller's classes. `collapse` is a static class in the template
     * and `collapsing` / `show` are written straight to `classList`, so the
     * three state classes stay out of OWL's `t-att-class` diffing — a patch
     * landing mid-animation would otherwise restore `collapse` (and with it
     * `display: none`) under the running animation.
     *
     * @returns {Object} merged CSS class object for the collapsible element
     */
    get classObj() {
        return mergeClasses(this.props.class);
    }

    /**
     * @param {boolean} open
     * @param {boolean} animate - false on the first pass, so a region that
     *  starts open does not play an opening animation on mount.
     */
    setOpen(open, animate) {
        const el = this.contentRef.el;
        if (!el) {
            return;
        }
        const dimension = this.props.horizontal ? "width" : "height";

        // Read before cancelling: `cancel` drops the element straight back to
        // its un-animated size, and the animation has to start from whatever is
        // on screen. Anchoring the keyframe to the full size instead made a
        // reversal jump there first -- toggling twice inside the 350ms window
        // snapped a half-open region to its full height before collapsing it.
        const from = `${el.getBoundingClientRect()[dimension]}px`;
        this.animation?.cancel();

        // `.collapse:not(.show)` is `display: none`, which zeroes scrollHeight.
        // The class has to come off before the full size can be measured.
        el.classList.remove("collapse", "show");
        el.classList.add("collapsing");

        const full = `${this.props.horizontal ? el.scrollWidth : el.scrollHeight}px`;
        const reduced = browser.matchMedia("(prefers-reduced-motion: reduce)").matches;
        const duration =
            animate && !reduced
                ? /** @type {any} */ (this.constructor).animationTime
                : 0;

        this.animation = el.animate(
            { [dimension]: [from, open ? full : "0px"] },
            duration,
        );
        this.animation.finished.then(
            () => {
                this.animation = null;
                // A settled region is sized by its content, never by the keyframe it
                // arrived on: `.show` and `display: none` are what hold it open or
                // shut from here.
                el.style.removeProperty(dimension);
                el.classList.remove("collapsing");
                el.classList.add("collapse");
                el.classList.toggle("show", open);
            },
            () => {},
        );
    }
}
