// @ts-check
/** @odoo-module native */

import { markRaw, reactive } from "@odoo/owl";
import { rootIdOf } from "@web/ui/overlay/root_id";

const SERVICE_OPTIONS = ["env", "onClose", "sequence", "useBottomSheet"];

const PRESENTER_SUPPLIED = ["close", "component", "componentProps", "slots", "target"];

/**
 * Every component a presenter can render. `usePopover`'s `useBottomSheet` hands
 * one option bag to whichever presenter the breakpoint selects, so the contract
 * the caller writes against is the union of them -- judging that bag against one
 * component alone reports the other's options as unknown, which is five warnings
 * per dropdown open on a touch device.
 *
 * Only the warning reads this. What each presenter *forwards* is still decided
 * by its own `toProps`, so an option meant for the other side is still ignored,
 * just not announced as a mistake.
 *
 * @type {Set<import("@odoo/owl").ComponentConstructor>}
 */
const PRESENTED_COMPONENTS = new Set();

/** @type {{ size: number, options: Set<string> } | null} */
let acceptedCache = null;

/**
 * @returns {Set<string>}
 */
function acceptedOptions() {
    if (acceptedCache?.size === PRESENTED_COMPONENTS.size) {
        return acceptedCache.options;
    }
    const accepted = new Set(SERVICE_OPTIONS);
    for (const component of PRESENTED_COMPONENTS) {
        for (const name of Object.keys(/** @type {any} */ (component).props ?? {})) {
            accepted.add(name);
        }
    }
    for (const name of PRESENTER_SUPPLIED) {
        accepted.delete(name);
    }
    acceptedCache = { size: PRESENTED_COMPONENTS.size, options: accepted };
    return accepted;
}

/**
 * @param {string} scope
 * @param {object} options
 * @param {Set<string>} accepted
 */
export function warnUnknownOptions(scope, options, accepted) {
    for (const key in options) {
        if (!accepted.has(key)) {
            console.warn(`[${scope}] unknown option "${key}"; it will be ignored.`);
        }
    }
}

/**
 * @type {Record<string, any>}
 */
export const PRESENTED_PROPS = {
    close: { type: Function },
    componentProps: { optional: true, type: Object },

    class: { optional: true },
    id: { optional: true, type: String },
    role: { optional: true, type: String },

    closeOnClickAway: { optional: true, type: Function },
    closeOnEscape: { optional: true, type: Boolean },
    setActiveElement: { optional: true, type: Boolean },

    ref: { optional: true, type: Function },

    presentation: { optional: true, type: Object },
};

/**
 * @param {boolean | ((target: HTMLElement) => boolean) | undefined} value
 * @returns {(target: HTMLElement) => boolean}
 */
function asPredicate(value) {
    return typeof value === "function" ? value : () => value ?? true;
}

/**
 * @param {any} options
 * @returns {object}
 */
function commonProps(options) {
    return {
        class: options.class,
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
 * @param {(options: any, target: HTMLElement) => object} config.toProps
 * @param {string} [config.scope]
 * @param {(options: any) => void} [config.onOpen]
 * @param {() => void} [config.onClosed]
 * @returns {(target: HTMLElement, component: any, props?: object, options?: any) => (removeParams?: any) => Promise<void>}
 */
export function makeOverlayPresenter({
    overlay,
    component,
    toProps,
    scope,
    onOpen,
    onClosed,
}) {
    PRESENTED_COMPONENTS.add(component);
    acceptedCache = null;
    return (target, hostedComponent, props = {}, options = {}) => {
        warnUnknownOptions(scope ?? "overlay", options, acceptedOptions());
        // The overlay is torn down only once the caller's onClose has settled,
        // and that can be a round trip. Until then it is still on screen and
        // still takes clicks, so say so and stop taking them.
        const presentation = reactive({ isClosing: false });
        const remove = overlay.add(
            component,
            {
                ...commonProps(options),
                ...toProps(options, target),
                component: hostedComponent,
                componentProps: markRaw(props),
                presentation,
                close: (/** @type {any} */ removeParams) => remove(removeParams),
            },
            {
                env: options.env,
                sequence: options.sequence,
                rootId: rootIdOf(target),
                onRemove: async (/** @type {any} */ removeParams) => {
                    presentation.isClosing = true;
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
