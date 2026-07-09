// @ts-check
/** @odoo-module native */

/** @module @web/fields/hooks/record_observer - OWL hook for observing record value changes in field components */

import { onWillDestroy, onWillStart, onWillUpdateProps, useComponent } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { Deferred } from "@web/core/utils/concurrency";
import { uniqueId } from "@web/core/utils/functions";
import { disposableEffect } from "@web/core/utils/reactive";
import { batched } from "@web/core/utils/timing";

/**
 * This hook should only be used in a component field because it
 * depends on the record props.
 * The callback will be executed once during setup and each time
 * a record value read in the callback changes.
 * @param {(record: any, props?: any) => void | Promise<void>} callback
 */
export function useRecordObserver(callback) {
    const component = useComponent();
    let currentId;
    // Disposer of the currently-active reactive effect. Each record swap and
    // the component teardown dispose the previous effect, so a superseded
    // effect no longer fires (and no longer allocates a batched rAF) on every
    // mutation of a record this component no longer observes.
    let disposeEffect;
    const observeRecord = (props) => {
        currentId = uniqueId();
        disposeEffect?.();
        disposeEffect = undefined;
        if (!props.record) {
            return;
        }
        const def = new Deferred();
        const effectId = currentId;
        let firstCall = true;
        // A single batched instance so that all effect notifications within the
        // same animation frame coalesce into one callback invocation.
        const batchedCallback = batched(
            (record) => {
                if (effectId !== currentId) {
                    // effect doesn't clean up when the component is unmounted.
                    // We must do it manually.
                    return;
                }
                return Promise.resolve(callback(record, props))
                    .then(def.resolve)
                    .catch(def.reject);
            },
            () =>
                new Promise((resolve) =>
                    browser.requestAnimationFrame(() => resolve()),
                ),
        );
        disposeEffect = disposableEffect(
            (record) => {
                if (firstCall) {
                    firstCall = false;
                    return Promise.resolve(callback(record, props))
                        .then(def.resolve)
                        .catch(def.reject);
                } else {
                    return batchedCallback(record);
                }
            },
            [props.record],
        );
        return def;
    };
    onWillDestroy(() => {
        currentId = uniqueId();
        disposeEffect?.();
        disposeEffect = undefined;
    });
    onWillStart(async () => {
        await observeRecord(component.props);
    });
    onWillUpdateProps(async (nextProps) => {
        if (nextProps.record !== component.props.record) {
            await observeRecord(nextProps);
        }
    });
}
