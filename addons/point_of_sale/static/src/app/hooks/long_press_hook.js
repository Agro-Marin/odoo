/** @odoo-module native */
import { onWillUnmount } from "@odoo/owl";
import { LONG_PRESS_DURATION } from "@point_of_sale/utils";

export function useLongPress(callback, delay = LONG_PRESS_DURATION) {
    let timer = null;

    function startLongPress(params) {
        timer = setTimeout(() => {
            callback(params);
        }, delay);
    }

    function cancelLongPress() {
        if (timer) {
            clearTimeout(timer);
            timer = null;
        }
    }

    // If the component unmounts mid-press, cancel the pending timer so the
    // callback can't fire against a torn-down component.
    onWillUnmount(cancelLongPress);

    return {
        onMouseDown(event, params) {
            if (event.button === 0) {
                startLongPress(params);
            }
        },
        onMouseUp: cancelLongPress,
        onTouchStart(params) {
            startLongPress(params);
        },
        onTouchEnd: cancelLongPress,
        onScroll: cancelLongPress,
    };
}
