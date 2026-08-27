// @ts-check
/** @odoo-module native */

import {
    onWillDestroy,
    onWillUpdateProps,
    status,
    useComponent,
    useState,
} from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { useRecordObserver } from "@web/fields/hooks/record_observer";
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
    const { specialDataCaches } = record.model;
    const orm = useService("orm");
    let loadTicket = 0;
    let appliedTicket = 0;
    const apply = (ticket, data) => {
        if (ticket >= appliedTicket) {
            appliedTicket = ticket;
            result.data = data;
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
    useRecordObserver(async (record, props) => {
        const ticket = ++loadTicket;
        apply(ticket, await loadFn(ormWithCache, { ...props, record }));
    });
    onWillUpdateProps(async (props) => {
        if (props.record.id === component.props.record.id) {
            const ticket = ++loadTicket;
            apply(ticket, await loadFn(ormWithCache, props));
        }
    });
    return result;
}
