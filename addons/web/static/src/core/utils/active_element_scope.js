// @ts-check
/** @odoo-module native */

import { useChildSubEnv, useComponent } from "@odoo/owl";
import { getComponentElement } from "@web/core/utils/components";

const ACTIVE_ELEMENT_SCOPE = Symbol("ui.activeElementScope");

/**
 * @type {WeakMap<object, { el: HTMLElement | null }>}
 */
const OWN_SCOPES = new WeakMap();

/**
 * @type {(node: Node) => Document | HTMLElement}
 */
let enclosingScopeOf = () => document;

/**
 * @param {(node: Node) => Document | HTMLElement} resolve
 * @returns {() => void}
 */
export function publishEnclosingScopeResolver(resolve) {
    enclosingScopeOf = resolve;
    return () => {
        enclosingScopeOf = () => document;
    };
}

/**
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
        if (own?.el) {
            return own.el;
        }
        const el = getComponentElement(component);
        return el ? enclosingScopeOf(el) : document;
    };
}
