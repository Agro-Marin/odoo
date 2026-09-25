// @ts-check
/** @odoo-module native */

import { Component, onWillDestroy, useComponent, xml } from "@odoo/owl";

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

/**
 * @template {string} K
 * @typedef {K extends keyof HTMLElementEventMap
 *     ? HTMLElementEventMap[K]
 *     : K extends keyof WindowEventMap
 *       ? WindowEventMap[K]
 *       : K extends keyof DocumentEventMap
 *         ? DocumentEventMap[K]
 *         : any} ListenedEvent
 */

/**
 * @template {string} K
 * @param {EventTarget} target
 * @param {K} eventName
 * @param {(ev: ListenedEvent<K>) => unknown} handler
 * @param {boolean | AddEventListenerOptions} [eventParams]
 */
export function useListener(target, eventName, handler, eventParams) {
    // OWL 2 twin of OWL 3's useListener: attached at setup, removed on destroy,
    // handler unbound; the event being dispatched while a component is set up
    // (window.event survives the microtasks between its listeners) is skipped
    const attachedDuring = window.event;
    const listener = (/** @type {Event} */ ev) => {
        if (ev !== attachedDuring) {
            handler.call(target, /** @type {ListenedEvent<K>} */ (ev));
        }
    };
    target.addEventListener(eventName, listener, eventParams);
    onWillDestroy(() => target.removeEventListener(eventName, listener, eventParams));
}

export class Portal extends Component {
    // OWL 2 twin of OWL 3's Portal component, which replaces the t-portal directive
    static template = xml`<t t-portal="this.props.target"><t t-slot="default"/></t>`;
    static props = { target: String, slots: Object };
}
