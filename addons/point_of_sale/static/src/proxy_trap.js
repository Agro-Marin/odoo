/** @odoo-module native */
export class TrapDisabler {
    constructor() {
        this.disabled = 0;
    }
    isDisabled() {
        return this.disabled > 0;
    }
    call(fn, ...args) {
        try {
            this.disabled += 1;
            return fn(...args);
        } finally {
            this.disabled -= 1;
        }
    }
}

const disablerCaches = new WeakMap();

export function getDisabler(target, prop) {
    if (!disablerCaches.has(target)) {
        disablerCaches.set(target, new Map());
    }
    const disablerCache = disablerCaches.get(target);
    if (!disablerCache.has(prop)) {
        disablerCache.set(prop, new TrapDisabler());
    }
    return disablerCache.get(prop);
}
