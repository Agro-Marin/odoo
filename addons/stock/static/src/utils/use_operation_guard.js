/** @odoo-module native */
import { useState } from "@odoo/owl";

/**
 * Re-entrancy guard for mutating handlers (reserve/unreserve, assign, order,
 * snooze, ...): wraps an async handler so that a second activation while the
 * first is still awaited is a no-op, and exposes a reactive `busy` flag the
 * template can bind to (e.g. `t-att-disabled="opGuard.busy"`) to disable the
 * controls during the await.
 *
 * Usage:
 *     setup() {
 *         this.opGuard = useOperationGuard();
 *         this.onClickSave = this.opGuard.guard(this.onClickSave.bind(this));
 *     }
 *
 * All handlers wrapped by the same instance share one busy flag: while any of
 * them is in flight, all of them are inert.
 */
export function useOperationGuard() {
    const state = useState({ busy: false });
    return {
        get busy() {
            return state.busy;
        },
        guard(fn) {
            return async (...args) => {
                if (state.busy) {
                    return;
                }
                state.busy = true;
                try {
                    return await fn(...args);
                } finally {
                    state.busy = false;
                }
            };
        },
    };
}
