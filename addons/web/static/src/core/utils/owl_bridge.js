// @ts-check
/** @odoo-module native */

import { useComponent } from "@odoo/owl";

/**
 * @returns {Record<string, any>}
 */
export function useProps() {
    // OWL 2 twin of OWL 3's props(): a live view of the calling component's
    // props, so a hook needs no handle on the component itself
    const component = useComponent();
    return new Proxy(Object.create(null), {
        get: (_target, key) => component.props[key],
        has: (_target, key) => key in component.props,
        set: (_target, key, value) => Reflect.set(component.props, key, value),
        deleteProperty: (_target, key) => Reflect.deleteProperty(component.props, key),
        ownKeys: () => Reflect.ownKeys(component.props),
        getOwnPropertyDescriptor: (_target, key) => {
            const descriptor = Reflect.getOwnPropertyDescriptor(component.props, key);
            return descriptor && { ...descriptor, configurable: true };
        },
    });
}

/**
 * @returns {string}
 */
export function useComponentName() {
    // OWL 2 twin of OWL 3's getComponentScope().componentName
    return useComponent().constructor.name;
}
