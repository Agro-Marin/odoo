// @ts-check
/** @odoo-module native */

import {
    onWillDestroy,
    onWillRender,
    onWillStart,
    reactive,
    status,
    toRaw,
    useComponent,
    useState,
} from "@odoo/owl";
import { deepEqual } from "@web/core/utils/collections/objects";
import { useService } from "@web/core/utils/hooks";
/** @import { Component } from "@odoo/owl" */
/** @import { Services } from "services" */

/**
 * @type {WeakMap<Map<string, Promise<any>>, Map<string, Set<() => void>>>}
 */
const staleReloadSubscribers = new WeakMap();

/**
 * @param {Map<string, Promise<any>>} specialDataCaches
 * @param {string} key
 * @returns {Set<() => void>}
 */
function subscribersFor(specialDataCaches, key) {
    let byKey = staleReloadSubscribers.get(specialDataCaches);
    if (!byKey) {
        byKey = new Map();
        staleReloadSubscribers.set(specialDataCaches, byKey);
    }
    let subscribers = byKey.get(key);
    if (!subscribers) {
        subscribers = new Set();
        byKey.set(key, subscribers);
    }
    return subscribers;
}

/**
 * @template T, [Props=any]
 * @param {(orm: Services["orm"], props: Component<Props>["props"]) => Promise<T>} loadFn
 * @returns {{ data: T }}
 */
export function useSpecialData(loadFn) {
    const component = useComponent();
    const record = component.props.record;
    // The raw map: it is plumbing shared by every widget on the model, and
    // read through the record's reactive proxy every write to it would
    // re-render whoever last read it -- which is this component, at each load.
    const specialDataCaches = toRaw(record.model.specialDataCaches);
    const orm = useService("orm");
    let loadTicket = 0;
    let appliedTicket = 0;
    // Equal data is not applied: a loader that assembles its result from two
    // calls returns a fresh array each time, and assigning it would re-render,
    // which reloads, which assembles another -- without end.
    const apply = (ticket, data) => {
        if (ticket >= appliedTicket) {
            appliedTicket = ticket;
            if (!deepEqual(toRaw(result.data), data)) {
                renderFromApply = true;
                result.data = data;
            }
        }
    };
    function reloadOnStaleCache() {
        if (status(component) === "destroyed") {
            return;
        }
        const ticket = ++loadTicket;
        loadFn(ormWithCache, component.props).then((res) => apply(ticket, res));
    }

    const joinedSubscribers = new Set();
    onWillDestroy(() => {
        for (const subscribers of joinedSubscribers) {
            subscribers.delete(reloadOnStaleCache);
        }
        joinedSubscribers.clear();
    });

    const ormWithCache = Object.create(orm);
    ormWithCache.call = (/** @type {Parameters<typeof orm.call>} */ ...args) => {
        const key = JSON.stringify(args);
        const subscribers = subscribersFor(specialDataCaches, key);
        subscribers.add(reloadOnStaleCache);
        joinedSubscribers.add(subscribers);
        if (!specialDataCaches.has(key)) {
            /** @type {(value: any) => void} */
            let deliver;
            const delivered = new Promise((resolve) => {
                deliver = resolve;
            });
            const prom = orm
                .cache({
                    type: "disk",
                    update: "always",
                    callback: (res, hasChanged) => {
                        deliver(res);
                        specialDataCaches.set(key, Promise.resolve(res));
                        if (!hasChanged) {
                            return;
                        }
                        for (const subscriber of [...subscribers]) {
                            subscriber();
                        }
                    },
                })
                .call(...args);
            const settled = Promise.race([prom, delivered]);
            specialDataCaches.set(key, settled);
            prom.catch(() => {
                if (specialDataCaches.get(key) === settled) {
                    specialDataCaches.delete(key);
                }
            });
        }
        return specialDataCaches.get(key);
    };

    /** @type {{ data: T }} */
    const result = useState(/** @type {any} */ ({ data: {} }));
    let renderFromApply = false;
    const rerender = () => {
        if (status(component) !== "destroyed") {
            component.render();
        }
    };
    const load = () => {
        const ticket = ++loadTicket;
        // The record is read through a proxy bound to this component's own
        // render: a prop is bound to the parent's, so reads through it would
        // re-render the parent and leave this widget -- whose props did not
        // change -- exactly where it was.
        const props = { ...component.props };
        if (props.record) {
            props.record = reactive(props.record, rerender);
        }
        return loadFn(ormWithCache, props).then((res) => apply(ticket, res));
    };
    // The loader runs before the first render and again before every later
    // one, except the render that applying its own result caused. What it
    // reads of the record -- the domain's dependencies, the current ids --
    // subscribes this component to those fields, so an edit that changes the
    // domain re-renders and reloads while an unrelated edit does neither. A
    // reload whose inputs did not change hits the args-keyed cache.
    onWillStart(load);
    let firstRender = true;
    onWillRender(() => {
        if (firstRender || renderFromApply) {
            firstRender = false;
            renderFromApply = false;
            return;
        }
        load();
    });
    return result;
}
