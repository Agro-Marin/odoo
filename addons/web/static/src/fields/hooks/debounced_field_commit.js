// @ts-check
/** @odoo-module native */

import { useComponent } from "@odoo/owl";
import { ModelEvent } from "@web/core/events";
import { useBus } from "@web/core/utils/hooks";
import { useDebounced } from "@web/core/utils/timing";

/**
 * @param {() => Promise<any> | undefined | void} commit
 * @param {number} delay
 * @returns {ReturnType<typeof useDebounced>}
 */
export function useDebouncedFieldCommit(commit, delay) {
    const component = /** @type {any} */ (useComponent());
    const debounced = useDebounced(commit, delay, { execBeforeUnmount: true });

    /** @param {any} ev */
    const flush = (ev) => {
        debounced.cancel();
        const prom = commit();
        if (prom) {
            ev.detail?.proms?.push(prom);
        }
    };

    useFieldFlush(component.props.record.model.bus, flush);

    return debounced;
}

/**
 * @param {import("@odoo/owl").EventBus} bus the record's model bus
 * @param {(ev: CustomEvent, urgent: boolean) => void} onFlush pushes its promise
 *  into ev.detail.proms when it has one
 */
export function useFieldFlush(bus, onFlush) {
    useBus(bus, ModelEvent.NEED_LOCAL_CHANGES, (ev) => onFlush(ev, false));
    useBus(bus, ModelEvent.WILL_SAVE_URGENTLY, (ev) => onFlush(ev, true));
}
