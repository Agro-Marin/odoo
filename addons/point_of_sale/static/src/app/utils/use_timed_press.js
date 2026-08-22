/** @odoo-module native */
import { onMounted, onWillUnmount } from "@odoo/owl";

/**
 * @param {Ref} ref
 * @param {Array<Object>} ranges
 * @param {number} [ranges[].delay=0]
 * @param {number} [ranges[].maxDelay]
 * @param {Function} ranges[].callback
 * @param {string} [ranges[].type="release"]
 */
export function useTimedPress(ref, ranges = []) {
    let timerStart = null;
    let holdTimers = [];

    const handlePointerDown = (event) => {
        if (event.button !== 0) {
            return;
        }
        timerStart = performance.now();

        for (const { delay = 0, type = "release", callback } of ranges) {
            if (type === "hold" && typeof callback === "function") {
                const timer = setTimeout(() => {
                    callback(event, delay);
                }, delay);
                holdTimers.push(timer);
            }
        }
    };

    const handlePointerUp = (event) => {
        if (timerStart === null) {
            return;
        }

        const elapsed = performance.now() - timerStart;
        timerStart = null;
        clearAllHoldTimers();

        for (const { delay = 0, maxDelay, type = "release", callback } of ranges) {
            if (type === "release" && typeof callback === "function") {
                if (
                    elapsed >= delay &&
                    (maxDelay === undefined || elapsed < maxDelay)
                ) {
                    callback(event, elapsed);
                }
            }
        }
    };

    const cancel = () => {
        timerStart = null;
        clearAllHoldTimers();
    };

    const clearAllHoldTimers = () => {
        for (const timer of holdTimers) {
            clearTimeout(timer);
        }
        holdTimers = [];
    };

    onMounted(() => {
        const el = ref.el;
        el?.addEventListener("pointerdown", handlePointerDown);
        el?.addEventListener("pointerup", handlePointerUp);
        el?.addEventListener("pointerleave", cancel);
        el?.addEventListener("pointercancel", cancel);
    });

    onWillUnmount(() => {
        const el = ref.el;
        el?.removeEventListener("pointerdown", handlePointerDown);
        el?.removeEventListener("pointerup", handlePointerUp);
        el?.removeEventListener("pointerleave", cancel);
        el?.removeEventListener("pointercancel", cancel);
    });
}
