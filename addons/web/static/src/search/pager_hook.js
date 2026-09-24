// @ts-check
/** @odoo-module native */

import { onWillRender, useState } from "@odoo/owl";
import { provideViewConfig, useViewConfig } from "@web/core/view_config_hooks";

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
 * @property {() => number | Promise<number>} [updateTotal]
 * @property {boolean} [isEditable]
 * @property {boolean} [withAccessKey]
 */

/** @param {() => (PagerProps | undefined)} getProps */
export function usePager(getProps) {
    /** @type {Record<string, any>} */
    const pagerState = useState({});

    provideViewConfig({ ...useViewConfig(), pagerProps: pagerState });
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
