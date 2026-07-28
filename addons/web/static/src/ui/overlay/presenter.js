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
 * @returns {(target: HTMLElement, component: any, props?: object, options?: any) => () => void}
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
            for (const key of Object.keys(options)) {
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
                close: () => remove(),
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
