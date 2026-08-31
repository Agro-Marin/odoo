// @ts-check
/** @odoo-module native */

import { useComponent } from "@odoo/owl";
import { ModelEvent } from "@web/core/events";
import { useBus } from "@web/core/utils/hooks";
import { useDebounced } from "@web/core/utils/timing";

/**
 * The commit half of a field that stages its edits locally and writes them in
 * one go: a debounced write, flushed whenever the model asks for pending changes
 * and once more before the component goes away.
 *
 * `commit` decides for itself whether there is anything to write; it returns a
 * promise when there is and nothing when there is not. The promise is handed to
 * the model through `ev.detail.proms`, which is what makes a save wait for it —
 * a commit that returns nothing simply does not delay the save.
 *
 * Both checkbox widgets wrote this by hand and disagreed on the details:
 * `many2many_checkboxes` used a raw `debounce` with its own `onWillUnmount`, did
 * not cancel the pending timer before flushing on a bus event, and guarded
 * `ev.detail.proms` on one of the two events but not the other. Sharing the
 * protocol is what stops the next widget inheriting whichever copy it read.
 *
 * @param {() => Promise<any> | undefined | void} commit writes the staged edits
 * @param {number} delay debounce, in ms
 * @returns {ReturnType<typeof useDebounced>} schedules a debounced commit
 */
export function useDebouncedFieldCommit(commit, delay) {
    const component = /** @type {any} */ (useComponent());
    const debounced = useDebounced(commit, delay, { execBeforeUnmount: true });

    /** @param {any} ev */
    const flush = (ev) => {
        // Cancel first: the model is asking for the changes *now*, so letting
        // the timer survive would fire a second, empty commit later.
        debounced.cancel();
        const prom = commit();
        if (prom) {
            ev.detail?.proms?.push(prom);
        }
    };

    const { bus } = component.props.record.model;
    useBus(bus, ModelEvent.NEED_LOCAL_CHANGES, flush);
    useBus(bus, ModelEvent.WILL_SAVE_URGENTLY, flush);

    return debounced;
}
