// @ts-check
/** @odoo-module native */

/**
 * @type {Map<Node, { observer: MutationObserver, watchers: Map<Node, Set<() => void>> }>}
 */
const watchersByRoot = new Map();

/**
 * @param {Node} root
 */
function checkRoot(root) {
    const entry = watchersByRoot.get(root);
    if (!entry) {
        return;
    }
    /**
     * @type {Node[] | undefined}
     */
    let detached;
    for (const target of entry.watchers.keys()) {
        if (!target.isConnected) {
            (detached ??= []).push(target);
        }
    }
    if (!detached) {
        return;
    }
    for (const target of detached) {
        const callbacks = entry.watchers.get(target);
        if (!callbacks) {
            continue;
        }
        for (const callback of [...callbacks]) {
            callback();
        }
    }
}

/**
 * @param {Node} target
 * @param {() => void} onDetached
 * @returns {() => void}
 */
export function watchForDetachedTarget(target, onDetached) {
    const root = target.isConnected ? target.getRootNode() : document;
    let entry = watchersByRoot.get(root);
    if (!entry) {
        const observer = new MutationObserver(() => checkRoot(root));
        observer.observe(root, { childList: true, subtree: true });
        entry = { observer, watchers: new Map() };
        watchersByRoot.set(root, entry);
    }
    let callbacks = entry.watchers.get(target);
    if (!callbacks) {
        callbacks = new Set();
        entry.watchers.set(target, callbacks);
    }
    callbacks.add(onDetached);

    return () => {
        const current = watchersByRoot.get(root);
        const targetCallbacks = current?.watchers.get(target);
        if (!current || !targetCallbacks) {
            return;
        }
        targetCallbacks.delete(onDetached);
        if (!targetCallbacks.size) {
            current.watchers.delete(target);
        }
        if (!current.watchers.size) {
            current.observer.disconnect();
            watchersByRoot.delete(root);
        }
    };
}

/** @returns {number} */
export function getDetachedTargetObserverCount() {
    return watchersByRoot.size;
}
