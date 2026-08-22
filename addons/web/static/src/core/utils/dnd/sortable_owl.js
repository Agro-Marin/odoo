// @ts-check
/** @odoo-module native */

import { onWillUnmount, reactive, useEffect, useExternalListener } from "@odoo/owl";
import { useSortable as nativeUseSortable } from "@web/core/utils/dnd/sortable";
import { useThrottleForAnimation } from "@web/core/utils/timing";

/**
 * @type {typeof nativeUseSortable}
 */
export function useSortable(params) {
    return nativeUseSortable(
        /** @type {any} */ ({
            ...params,
            setupHooks: {
                addListener: useExternalListener,
                setup: useEffect,
                teardown: onWillUnmount,
                throttle: useThrottleForAnimation,
                wrapState: reactive,
            },
        }),
    );
}
