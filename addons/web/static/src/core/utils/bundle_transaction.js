// @ts-check
/** @odoo-module native */

/**
 * A bundle is a unit: its registry contributions take effect together.
 *
 * Loading a lazy bundle evaluates its modules through parallel dynamic
 * `import()`s, and every `await` between them hands control back to the
 * microtask queue. Anything that reacts to a registry `UPDATE` therefore sees
 * the bundle *half applied* -- some modules evaluated, the rest not -- and acts
 * on it.
 *
 * That is not hypothetical. `portal.assets_chatter` carries both
 * `mail/core/common/chat_hub.js`, which registers the `mail.chat_hub` service,
 * and `portal/chatter/frontend/chat_hub_service_patch.js`, which patches that
 * service's `start()` to a no-op so the chat hub never mounts on a portal page.
 * `env.js` starts a service one microtask after it is registered, so the
 * unpatched `start()` could run first: it published `ChatHub` into
 * `main_components`, and the frontend app rendered a component whose template
 * module had not been evaluated yet -- `OwlError: Missing template
 * "mail.ChatHub"`, which is what made every website_slides tour red.
 *
 * The race was decided by how many microtask boundaries happened to sit between
 * two modules of the same bundle. This module removes the race rather than
 * widening the margin: while a bundle is being evaluated, reactions are held,
 * and they run once when the outermost evaluation finishes.
 *
 * Nesting is counted, so a bundle that loads another bundle settles only when
 * both are done.
 */

let depth = 0;

/** @type {Set<() => any>} */
const pending = new Set();

/**
 * Evaluate a bundle as one unit.
 *
 * @template T
 * @param {() => Promise<T>} evaluate
 * @returns {Promise<T>}
 */
export async function runInBundleTransaction(evaluate) {
    depth++;
    try {
        return await evaluate();
    } finally {
        depth--;
        if (depth === 0 && pending.size) {
            const callbacks = [...pending];
            pending.clear();
            // Awaited, so `loadBundle` resolves with the bundle *applied* and
            // not merely evaluated: a caller that loads a bundle in order to
            // use one of its services finds that service started.
            for (const callback of callbacks) {
                try {
                    await callback();
                } catch (error) {
                    console.error("[bundle] deferred callback failed:", error);
                }
            }
        }
    }
}

/**
 * Hold `callback` until every bundle in flight has finished evaluating.
 *
 * Identical callbacks collapse into one run, so N registrations inside one
 * bundle cost one reaction rather than N.
 *
 * @param {() => any} callback
 * @returns {boolean} true if it was held, false if nothing is in flight and the
 *   caller should run it itself.
 */
export function deferUntilBundlesSettled(callback) {
    if (depth === 0) {
        return false;
    }
    pending.add(callback);
    return true;
}

/** @returns {boolean} */
export function isBundleEvaluating() {
    return depth > 0;
}

/** Test helper: forget any held callback and reset the nesting counter. */
export function resetBundleTransactions() {
    depth = 0;
    pending.clear();
}
