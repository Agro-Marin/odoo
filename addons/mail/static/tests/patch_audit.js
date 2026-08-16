import { getPatchedTargets, patchInfo } from "@web/core/utils/patch";

/**
 * @param {object} target
 * @returns {string}
 */
export function patchTargetLabel(target) {
    if (typeof target === "function") {
        return target.name || "(anonymous function)";
    }
    const constructor = target?.constructor;
    if (constructor?.prototype === target && Object.hasOwn(target, "constructor")) {
        return `${constructor.name}.prototype`;
    }
    return constructor && constructor.name !== "Object"
        ? `(${constructor.name} instance)`
        : "(plain object)";
}

/** @returns {string[]} */
export function getDoublePatchedPairs() {
    const pairs = new Set();
    for (const target of getPatchedTargets()) {
        const info = patchInfo(target);
        const counts = new Map();
        for (const extension of info.extensions) {
            for (const key of Object.getOwnPropertyNames(extension)) {
                counts.set(key, (counts.get(key) ?? 0) + 1);
            }
        }
        const label = patchTargetLabel(target);
        for (const [key, count] of counts) {
            if (count >= 2) {
                pairs.add(`${label} :: ${key}`);
            }
        }
    }
    return [...pairs].sort();
}
