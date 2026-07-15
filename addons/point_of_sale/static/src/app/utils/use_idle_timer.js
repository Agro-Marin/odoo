/** @odoo-module native */
import { onWillUnmount, useExternalListener } from "@odoo/owl";

const UserPresenceEvents = [
    "mousemove",
    "mousedown",
    "touchmove",
    "click",
    "scroll",
    "keypress",
];

export function useIdleTimer(steps, onAlive) {
    const state = {
        timeout: new Set(steps.map((s) => s.timeout)),
        idle: false,
        time: 0,
    };

    const checkSteps = () => {
        for (const step of steps) {
            if (step.timeout === state.time * 1000 && !state.idle) {
                state.idle = step.action();
            }
        }
    };

    const onMove = (ev) => {
        if (state.idle) {
            state.idle = onAlive(ev);
        }
        state.time = 0;
    };

    for (const event of UserPresenceEvents) {
        useExternalListener(window, event, onMove);
    }

    const intervalId = setInterval(() => {
        state.time++;
        if (state.timeout.has(state.time * 1000)) {
            checkSteps();
        }
    }, 1000);
    // Without this the 1 Hz interval outlives the component, keeps firing step
    // actions on a torn-down instance, and leaks one timer per mount.
    onWillUnmount(() => clearInterval(intervalId));

    return state;
}
