// @ts-check
/** @odoo-module native */

/** @module @web/fields/relational/special_data - OWL hook for loading and caching special data tied to a record lifecycle */

import { onWillUpdateProps, status, useComponent, useState } from "@odoo/owl";
import { useRecordObserver } from "@web/fields/hooks/record_observer";
/** @import { Component } from "@odoo/owl" */
/** @import { Services } from "services" */

/**
 * Hook for loading and caching special data (e.g. selection options) tied to a
 * record's lifecycle. Uses ORM disk cache with change detection to keep the
 * data fresh across record navigation.
 *
 * @template T, [Props=any]
 * @param {(orm: Services["orm"], props: Component<Props>["props"]) => Promise<T>} loadFn
 * @returns {{ data: T }}
 */
export function useSpecialData(loadFn) {
    const component = useComponent();
    const record = component.props.record;
    const { specialDataCaches } = record.model;
    const orm = component.env.services.orm;
    const ormWithCache = Object.create(orm);
    ormWithCache.call = (...args) => {
        const key = JSON.stringify(args);
        if (!specialDataCaches[key]) {
            // Store the in-flight promise synchronously so concurrent first
            // calls share it instead of re-entering the RPC cache layer.
            const prom = orm
                .cache({
                    type: "disk",
                    update: "always",
                    callback: (res, hasChanged) => {
                        specialDataCaches[key] = Promise.resolve(res);
                        if (status(component) !== "destroyed" && hasChanged) {
                            assign(
                                loadFn(ormWithCache, component.props),
                                component.props.record,
                            );
                        }
                    },
                })
                .call(...args);
            specialDataCaches[key] = prom;
            prom.catch(() => {
                // Do not cache failures: the next call must retry.
                if (specialDataCaches[key] === prom) {
                    delete specialDataCaches[key];
                }
            });
        }
        return specialDataCaches[key];
    };

    /** @type {{ data: T }} */
    const result = useState(/** @type {any} */ ({ data: {} }));
    // Guard every load against navigating away: a load fired for one record
    // must not clobber ``result.data`` once the component has moved to another
    // record. We deliberately do NOT serialize with ``KeepLast`` here — that
    // makes superseded loads hang, so on a same-record change (e.g. a dynamic
    // domain re-evaluating) only the batched record-observer assignment
    // survives, and that lone batched write does not schedule a re-render,
    // leaving the widget showing stale data. Assigning on each (idempotent,
    // same-record) load keeps the render reactive.
    const assign = async (promise, forRecord) => {
        const data = await promise;
        if (
            component.props.record.id === forRecord.id &&
            status(component) !== "destroyed"
        ) {
            result.data = data;
        }
    };
    useRecordObserver(async (record, props) => {
        await assign(loadFn(ormWithCache, { ...props, record }), record);
    });
    onWillUpdateProps(async (props) => {
        // useRecordObserver callback is not called when the record doesn't change
        if (props.record.id === component.props.record.id) {
            await assign(loadFn(ormWithCache, props), props.record);
        }
    });
    return result;
}
