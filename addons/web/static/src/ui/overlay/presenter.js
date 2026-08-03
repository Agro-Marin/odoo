// @ts-check
/** @odoo-module native */

/** @module @web/ui/overlay/presenter */

import { markRaw } from "@odoo/owl";

/**
 * Options handled by every presenter, whatever it presents.
 */
const COMMON_PRESENTER_OPTIONS = [
    "class",
    "closeOnClickAway",
    "closeOnEscape",
    "env",
    "id",
    "onClose",
    "popoverClass",
    "ref",
    "role",
    "sequence",
    "setActiveElement",
    "useBottomSheet",
];

const acceptedOptions = new Set(COMMON_PRESENTER_OPTIONS);

/**
 * Records the options one presenter consumes, so that the set the debug check
 * accepts is the union of what the presenters actually read rather than a
 * hand-kept list that drifts from them.
 *
 * The union, not per-presenter sets: `usePopover({ useBottomSheet })` routes one
 * options object to whichever presenter the breakpoint selects, so a `position`
 * reaching the bottom sheet is that API working, not a mistake.
 *
 * Call at module scope: a presenter is built when its service starts, which is
 * later than another presenter may first be used.
 *
 * @param {string[]} names
 * @returns {string[]}
 */
export function declarePresenterOptions(names) {
    for (const name of names) {
        acceptedOptions.add(name);
    }
    return names;
}

/**
 * @param {HTMLElement} target
 * @returns {string | undefined}
 */
export function rootIdOf(target) {
    return /** @type {ShadowRoot} */ (target?.getRootNode())?.host?.id;
}

/**
 * @param {boolean | ((target: HTMLElement) => boolean) | undefined} value
 * @returns {(target: HTMLElement) => boolean}
 */
export function asPredicate(value) {
    return typeof value === "function" ? value : () => value ?? true;
}

/**
 * The props every presented component takes, mapped once here rather than
 * per presenter. Kept identical on purpose: `usePopover({ useBottomSheet })`
 * hands ONE options object to whichever presenter the breakpoint picks, so any
 * option these two read differently is a behaviour change on rotation alone.
 *
 * Defaults deliberately stay OUT of this: an option left undefined must fall
 * through to the presented component's own `defaultProps`, so that the class
 * used directly in a template behaves the same as one reached through the
 * service. `setActiveElement` was defaulted here instead, which is why a
 * `<Popover>` written in a template trapped no focus while a `<BottomSheet>`
 * did.
 *
 * @param {any} options
 * @returns {object}
 */
function commonProps(options) {
    return {
        class: options.class ?? options.popoverClass,
        closeOnClickAway: asPredicate(options.closeOnClickAway),
        closeOnEscape: options.closeOnEscape,
        id: options.id,
        ref: options.ref,
        role: options.role,
        setActiveElement: options.setActiveElement,
    };
}

/**
 * @param {object} config
 * @param {any} config.overlay
 * @param {import("@odoo/owl").ComponentConstructor} config.component
 * @param {(options: any) => object} config.toProps
 * @param {(options: any) => void} [config.onOpen]
 * @param {() => void} [config.onClosed]
 * @returns {(target: HTMLElement, component: any, props?: object, options?: any) => (removeParams?: any) => Promise<void>}
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
            for (const key in options) {
                if (!acceptedOptions.has(key)) {
                    console.warn(
                        `[overlay] unknown option "${key}"; it will be ignored.`,
                    );
                }
            }
        }
        // toProps runs once, here, and its result is spread into a plain object:
        // an option defined as a getter is read exactly once and frozen at that
        // value for the overlay's whole life. Options describe the moment of
        // opening; anything that has to keep up with the opener afterwards has
        // to travel as props of the hosted component.
        const remove = overlay.add(
            component,
            {
                ...commonProps(options),
                ...toProps(options),
                target,
                component: hostedComponent,
                componentProps: markRaw(props),
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
