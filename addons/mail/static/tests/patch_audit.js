import { getPatchedTargets, patchDeclaredKeys, patchInfo } from "@web/core/utils/patch";

/**
 * @module @mail/../tests/patch_audit
 *
 * Diagnostic view over the live `patch()` graph, used by the double-patch
 * allowlist test (`core/patch_order_audit.test.js`) and handy from the
 * DevTools console when triaging "who else overrides this method?".
 *
 * Bundle glob order is an undeclared dependency system: when two modules
 * patch the same method of the same target, their `super` chain — hence
 * behavior — is defined by asset-bundle file order, which nothing asserts.
 * This module makes those collisions observable at runtime.
 */

/**
 * Human-readable label for a patch target. Class prototypes become
 * `"<Class>.prototype"`, classes/functions their own name, anything else an
 * opaque instance label. Two distinct classes with the same name (e.g. the
 * `Thread` model and the `Thread` component) share a label — acceptable for
 * an allowlist, since entries only ever get *more* specific by renaming.
 *
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

/**
 * List every `(target, method)` pair that is currently patched by two or
 * more extensions, as sorted `"<target label> :: <method>"` strings — the
 * exact places where bundle order silently decides the `super` chain.
 *
 * Only *live* patches count: extensions reverted by their unpatch function
 * (e.g. `patchWithCleanup` after a test) no longer appear.
 *
 * @returns {string[]}
 */
export function getDoublePatchedPairs() {
    const pairs = new Set();
    for (const target of getPatchedTargets()) {
        const info = patchInfo(target);
        const counts = new Map();
        for (const extension of info.extensions) {
            // Declared keys, not own keys: patch() copies previous descriptors
            // onto extensions when chaining `super`, so own-key inspection
            // counts a single patch of a pre-existing method as two owners.
            const keys =
                patchDeclaredKeys(extension) ?? Object.getOwnPropertyNames(extension);
            for (const key of keys) {
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
