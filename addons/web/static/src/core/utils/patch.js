// @ts-check
/** @odoo-module native */

/** @module @web/core/utils/patch */

/**
 * @typedef {{
 *      originalProperties: Map<string, PropertyDescriptor | undefined>;
 *      skeleton: object;
 *      extensions: Set<object>;
 *  }} PatchDescription
 */

/** @type {WeakMap<object, PatchDescription>} */
const patchDescriptions = new WeakMap();

/**
 * @type {WeakSet<object>}
 */
const usedExtensions = new WeakSet();

/**
 * @type {Set<WeakRef<object>>}
 */
const patchedTargetRefs = new Set();

/** @type {WeakSet<object>} */
const trackedTargets = new WeakSet();

/**
 * @param {object} objToPatch
 * @returns {PatchDescription}
 */
function getPatchDescription(objToPatch) {
    let description = patchDescriptions.get(objToPatch);
    if (!description) {
        description = {
            originalProperties: new Map(),
            skeleton: Object.create(Object.getPrototypeOf(objToPatch)),
            extensions: new Set(),
        };
        patchDescriptions.set(objToPatch, description);
    }
    return description;
}

/**
 * @param {object} objToPatch
 * @returns {boolean}
 */
function isClassPrototype(objToPatch) {
    return (
        Object.hasOwn(objToPatch, "constructor") &&
        objToPatch.constructor?.prototype === objToPatch
    );
}

/**
 * @param {object} objToPatch
 * @param {string} key
 * @returns {PropertyDescriptor | null}
 */
function findAncestorPropertyDescriptor(objToPatch, key) {
    let prototype = objToPatch;
    do {
        const descriptor = Object.getOwnPropertyDescriptor(prototype, key);
        if (descriptor) {
            return descriptor;
        }
        prototype = Object.getPrototypeOf(prototype);
    } while (prototype);
    return null;
}

/**
 * @template {Record<string, any>} T
 * @template {Partial<T>} U
 * @param {T} objToPatch
 * @param {U & ThisType<T & U>} extension
 * @returns {() => void}
 */
export function patch(objToPatch, extension) {
    if (typeof extension === "string") {
        throw new Error(
            `Patch "${extension}": Second argument is not the patch name anymore, it should be the object containing the patched properties`,
        );
    }

    if (usedExtensions.has(extension)) {
        throw new Error(
            "patch(): extension object already used in a patch. Each patch() call " +
                "needs its own fresh extension object (it is mutated to build the `super` chain).",
        );
    }

    const description = getPatchDescription(objToPatch);
    description.extensions.add(extension);
    usedExtensions.add(extension);
    if (!trackedTargets.has(objToPatch)) {
        trackedTargets.add(objToPatch);
        patchedTargetRefs.add(new WeakRef(objToPatch));
    }

    const properties = Object.getOwnPropertyDescriptors(extension);
    // Each patch stores the descriptors it shadows on its *own* skeleton,
    // chained after the previous extension. Writing them onto the previous
    // extension instead stamped foreign own-properties on an object the caller
    // still owns, which is what `extensionDeclaredKeys` used to exist to undo.
    const skeleton = Object.create(description.skeleton);
    for (const [key, newProperty] of Object.entries(properties)) {
        const oldProperty = Object.getOwnPropertyDescriptor(objToPatch, key);
        if (oldProperty) {
            Object.defineProperty(skeleton, key, oldProperty);
        }

        if (!description.originalProperties.has(key)) {
            description.originalProperties.set(key, oldProperty);
        }

        if (isClassPrototype(objToPatch)) {
            newProperty.enumerable = false;
        }

        if (Boolean(newProperty.get) !== Boolean(newProperty.set)) {
            const ancestorProperty = findAncestorPropertyDescriptor(objToPatch, key);
            newProperty.get = newProperty.get ?? ancestorProperty?.get;
            newProperty.set = newProperty.set ?? ancestorProperty?.set;
        }

        Object.defineProperty(objToPatch, key, newProperty);
    }

    // `super` resolves through the extension's own prototype (its methods'
    // [[HomeObject]]), so the extension must be the one re-parented.
    Object.setPrototypeOf(extension, skeleton);
    description.skeleton = extension;

    return () => {
        // Read the description back rather than closing over the one captured
        // above: unpatching re-applies the surviving extensions, and each of
        // those `patch()` calls builds a *fresh* description. A closure holding
        // the stale one would restore the wrong originals when two patches are
        // undone in registration order.
        const current = patchDescriptions.get(objToPatch);
        // Nothing left to undo: this closure already ran, or the target has
        // since been patched by someone else. Undoing anyway used to wipe that
        // unrelated patch and deregister it, so its own unpatch became a no-op.
        if (!current?.extensions.has(extension)) {
            return;
        }
        patchDescriptions.delete(objToPatch);

        for (const [key, property] of current.originalProperties) {
            if (property) {
                Object.defineProperty(objToPatch, key, property);
            } else {
                delete (/** @type {Record<string, any>} */ (objToPatch)[key]);
            }
        }

        current.extensions.delete(extension);
        usedExtensions.delete(extension);
        for (const survivor of current.extensions) {
            usedExtensions.delete(survivor);
            patch(objToPatch, survivor);
        }
    };
}

/**
 * @returns {object[]}
 */
export function getPatchedTargets() {
    const targets = [];
    for (const ref of patchedTargetRefs) {
        const target = ref.deref();
        if (!target) {
            patchedTargetRefs.delete(ref);
            continue;
        }
        if (patchDescriptions.has(target)) {
            targets.push(target);
        }
    }
    return targets;
}

/**
 * @param {object} target
 * @returns {{ extensions: object[], patchedKeys: string[] } | null}
 */
export function patchInfo(target) {
    const description = patchDescriptions.get(target);
    if (!description) {
        return null;
    }
    return {
        extensions: [...description.extensions],
        patchedKeys: [...description.originalProperties.keys()],
    };
}
