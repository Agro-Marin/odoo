// @ts-check
/** @odoo-module native */

/** @module @web/core/utils/dnd/sortable_owl - OWL-lifecycle adapter for useSortable with reactive state */

import { onWillUnmount, reactive, useEffect, useExternalListener } from "@odoo/owl";
import { useSortable as nativeUseSortable } from "@web/core/utils/dnd/sortable";
import { useThrottleForAnimation } from "@web/core/utils/timing";

/**
 * `useSortable` setup hooks wired to Owl's lifecycle and reactivity.
 *
 * @see {nativeUseSortable}
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
