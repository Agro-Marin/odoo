/** @odoo-module native */
import { onMounted, onWillUnmount } from "@odoo/owl";

/**
 * Hook that runs callbacks based on how long an element is pressed. Works with
 * mouse, touch and stylus via pointer events.
 *
 * @param {Ref} ref - OWL `useRef` pointing to the target element.
 * @param {Array<Object>} ranges - Press ranges, each with:
 *   @param {number} [ranges[].delay=0] - Minimum press duration (ms) to trigger.
 *   @param {number} [ranges[].maxDelay] - If set, only triggers below this duration.
 *   @param {Function} ranges[].callback - `(event: PointerEvent, duration: number) => void`.
 *   @param {string} [ranges[].type="release"] - `"hold"` fires while held past `delay`;
 *     `"release"` fires on release if duration is within `[delay, maxDelay)`.
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
