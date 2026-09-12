/** @odoo-module native */
import { onWillUnmount } from "@odoo/owl";
import { LONG_PRESS_DURATION } from "@point_of_sale/utils";
import { makeLogger } from "@web/core/debug/debug_logger";
const log = makeLogger("pos.press.long");

export function useLongPress(callback, delay = LONG_PRESS_DURATION) {
    let timer = null;

    function startLongPress(params) {
        timer = setTimeout(() => {
            log.logic("long press fired", () => ({
                delay,
                params: params?.id ?? params,
            }));
            callback(params);
        }, delay);
    }

    function cancelLongPress() {
        if (timer) {
            clearTimeout(timer);
            timer = null;
        }
    }

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
