// @ts-check

import { afterEach, onError } from "@odoo/hoot";

export function preventResizeObserverError() {
    let resizeObserverErrorCount = 0;
    onError((ev) => {
        if (
            /** @type {any} */ (ev).message ===
            "ResizeObserver loop completed with undelivered notifications."
        ) {
            if (resizeObserverErrorCount < 1) {
                ev.preventDefault();
            }
            resizeObserverErrorCount++;
        }
    });

    afterEach(() => {
        resizeObserverErrorCount = 0;
    });
}
