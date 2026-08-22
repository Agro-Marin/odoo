// @ts-check
/** @odoo-module native */

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
    /** @type {Record<string, any>} */
    const pagerState = useState({});

    useSubEnv({
        config: {
            ...env.config,
            pagerProps: pagerState,
        },
    });
    /** @type {string[]} */
    let previousKeys = [];
    onWillRender(() => {
        const props = getProps() || { total: 0 };
        for (const key of previousKeys) {
            if (!(key in props)) {
                delete pagerState[key];
            }
        }
        previousKeys = Object.keys(props);
        Object.assign(pagerState, props);
    });
}
