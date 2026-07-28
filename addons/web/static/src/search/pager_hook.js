// @ts-check
/** @odoo-module native */

/** @module @web/search/pager_hook - OWL hook that injects reactive pager props into the sub-environment */

import { onWillRender, useEnv, useState, useSubEnv } from "@odoo/owl";

/**
 * @typedef PagerUpdateParams
 * @property {number} offset
 * @property {number} limit
 */

/**
 * @typedef PagerProps
 * @property {number} offset
 * @property {number} limit
 * @property {number} total
 * @property {(params: PagerUpdateParams) => any} onUpdate
 * @property {boolean} [isEditable]
 * @property {boolean} [withAccessKey]
 */

/**
 * @param {() => (PagerProps | undefined)} getProps
 */
export function usePager(getProps) {
    const env = useEnv();
    const pagerState = useState({});

    useSubEnv({
        config: {
            ...env.config,
            pagerProps: pagerState,
        },
    });
    // Plain closure, never `Object.keys(pagerState)`: reading the reactive
    // object here would subscribe the owning component to its own key set, and
    // the writes below would then schedule a second render of every view that
    // pages.
    let previousKeys = [];
    onWillRender(() => {
        const props = getProps() || { total: 0 };
        // Replace, don't merge: `Object.assign` alone left every key the
        // previous render set and this one omits, so the ControlPanel spread
        // `<Pager t-props="pagerProps"/>` kept receiving it. Callers were
        // papering over that by hand — list_controller still writes
        // `updateTotal: <cond> ? fn : undefined` purely so the key gets
        // overwritten rather than inherited.
        for (const key of previousKeys) {
            if (!(key in props)) {
                delete pagerState[key];
            }
        }
        previousKeys = Object.keys(props);
        Object.assign(pagerState, props);
    });
}
