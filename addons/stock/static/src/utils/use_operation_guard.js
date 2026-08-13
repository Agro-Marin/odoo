/** @odoo-module native */
import { useState } from "@odoo/owl";

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
