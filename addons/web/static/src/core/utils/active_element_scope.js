// @ts-check
/** @odoo-module native */

import { useChildSubEnv, useComponent } from "@odoo/owl";
import { getComponentElement } from "@web/core/utils/components";

/**
 * Carries the owning active element down the component tree, as a holder rather
 * than the element itself: the owner publishes it during `setup`, which runs
 * parent-first, and fills it in an effect, which runs child-first.
 */
const ACTIVE_ELEMENT_SCOPE = Symbol("ui.activeElementScope");

/**
 * A component that activates an element is the owner of it, not a bystander
 * outside it: its own hotkeys belong to that element. The DOM cannot say so --
 * the component's root usually *wraps* the element rather than sitting inside
 * it -- so ownership is recorded here.
 *
 * @type {WeakMap<object, { el: HTMLElement | null }>}
 */
const OWN_SCOPES = new WeakMap();

/**
 * Which active element encloses a node is a question only the ui layer's active
 * element stack can answer, and core may not name the `ui` service to ask it.
 * So core declares the question here and ui answers it: `ui_service` publishes
 * its resolver on start and withdraws it on destroy. Until then -- and after --
 * the document is the enclosing scope, which is what an unblocked page means.
 *
 * @type {(node: Node) => Document | HTMLElement}
 */
let enclosingScopeOf = () => document;

/**
 * Publishes the ui layer's answer to {@link useActiveElementScope}'s fallback.
 *
 * @param {(node: Node) => Document | HTMLElement} resolve
 * @returns {() => void} withdraws it again
 */
export function publishEnclosingScopeResolver(resolve) {
    enclosingScopeOf = resolve;
    return () => {
        enclosingScopeOf = () => document;
    };
}

/**
 * Declares the calling component as the owner of an active element, and returns
 * the holder it must fill once that element exists.
 *
 * @returns {{ el: HTMLElement | null }}
 */
export function useOwnedActiveElement() {
    /** @type {{ el: HTMLElement | null }} */
    const scope = { el: null };
    OWN_SCOPES.set(useComponent(), scope);
    useChildSubEnv({ [ACTIVE_ELEMENT_SCOPE]: scope });
    return scope;
}

/**
 * The active element a component's registrations belong to.
 *
 * Answered from where the component sits: the element it activates itself if it
 * activates one, the nearest active element enclosing it in the DOM otherwise.
 * The alternative this replaced -- read `ui.activeElement` one microtask after
 * registering -- answers with whatever element is active when the deferral
 * fires, so an overlay opening in the same task silently takes ownership of
 * every hotkey and command registered beside it.
 *
 * @returns {() => Document | HTMLElement}
 */
export function useActiveElementScope() {
    const component = useComponent();
    return () => {
        const own =
            OWN_SCOPES.get(component) ??
            /** @type {Record<symbol, { el: HTMLElement | null }>} */ (component.env)[
                ACTIVE_ELEMENT_SCOPE
            ];
        return own?.el ?? enclosingScopeOf(getComponentElement(component));
    };
}
