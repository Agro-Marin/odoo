// @ts-check
/** @odoo-module native */

/** @module @web/ui/overlay/presenter - Shared plumbing for services that present a component in an overlay */

import { markRaw } from "@odoo/owl";

/**
 * The option names understood by every presenter built here. Both the popover
 * and the bottom sheet accept the whole set so `usePopover` can hand the same
 * bag to either backend; each declares which subset it actually renders, and
 * anything outside this list is a caller mistake rather than a silent no-op.
 */
export const OVERLAY_PRESENTER_OPTIONS = new Set([
    "animation",
    "arrow",
    "class",
    "closeOnClickAway",
    "closeOnEscape",
    "env",
    "extendedFlipping",
    "fixedPosition",
    "holdOnHover",
    "onBack",
    "onClose",
    "onPositioned",
    "popoverClass",
    "position",
    "preventDismissOnContentScroll",
    "ref",
    "role",
    "sequence",
    "setActiveElement",
    "useBottomSheet",
]);

/**
 * The shadow root a target lives in, or `undefined` for the main document.
 * Overlays are rendered by the `OverlayContainer` of their own root.
 *
 * @param {HTMLElement} target
 * @returns {string | undefined}
 */
export function rootIdOf(target) {
    return /** @type {ShadowRoot} */ (target?.getRootNode())?.host?.id;
}

/**
 * Normalise a boolean-or-predicate option into a predicate, so the hosted
 * component only ever deals with one shape. Lives here rather than in one
 * backend: `usePopover` hands the same option bag to the popover or to the
 * bottom sheet, and the two normalising it differently is how they drift.
 *
 * @param {boolean | ((target: HTMLElement) => boolean) | undefined} value
 * @param {boolean} [fallback]
 * @returns {(target: HTMLElement) => boolean}
 */
export function asPredicate(value, fallback = true) {
    return typeof value === "function" ? value : () => value ?? fallback;
}

/**
 * Build the `add` function of a service that shows `component` in an overlay.
 *
 * Owns what every such service repeated by hand: allocating the entry, wiring
 * `close` back to its own removal, scoping it to the target's shadow root, and
 * running teardown after the caller's `onClose` settles. Removal ordering is
 * deliberately left as `overlayService` defines it — `onClose` resolves before
 * the DOM goes away, which the action service relies on to keep a dialog up
 * until the view behind it has reloaded.
 *
 * @param {object} config
 * @param {any} config.overlay the overlay service
 * @param {import("@odoo/owl").ComponentConstructor} config.component
 * @param {(options: any) => object} config.toProps maps caller options to props
 *  of `config.component` (the hosted component and its props are added here)
 * @param {(options: any) => void} [config.onOpen] runs after the entry is added
 * @param {() => void} [config.onClosed] runs after the caller's `onClose`
 * @returns {(target: HTMLElement, component: any, props?: object, options?: any) => (removeParams?: any) => void}
 */
export function makeOverlayPresenter({
    overlay,
    component,
    toProps,
    onOpen,
    onClosed,
}) {
    return (target, hostedComponent, props = {}, options = {}) => {
        if (odoo.debug) {
            // `for...in`, not `Object.keys`: `makePopover` hands us an
            // `Object.create(options)` bag so it can override `onClose` without
            // mutating the caller's, which left every real option on the
            // prototype and own-key enumeration seeing only `onClose`. The
            // check was silently inert for `usePopover` — the path nearly every
            // caller takes.
            for (const key in options) {
                if (!OVERLAY_PRESENTER_OPTIONS.has(key)) {
                    console.warn(
                        `[overlay] unknown option "${key}"; it will be ignored.`,
                    );
                }
            }
        }
        const remove = overlay.add(
            component,
            {
                ...toProps(options),
                target,
                component: hostedComponent,
                componentProps: markRaw(props),
                /**
                 * Forwards its argument, like the dialog service's `close`
                 * does: a hosted component is the one place that knows WHY it
                 * is closing, and dropping that here made the reason
                 * unobservable from `onClose`.
                 */
                close: (/** @type {any} */ removeParams) => remove(removeParams),
            },
            {
                env: options.env,
                sequence: options.sequence,
                rootId: rootIdOf(target),
                onRemove: async (/** @type {any} */ removeParams) => {
                    try {
                        await options.onClose?.(removeParams);
                    } finally {
                        onClosed?.();
                    }
                },
            },
        );
        onOpen?.(options);
        return remove;
    };
}
