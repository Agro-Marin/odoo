// @ts-check
/** @odoo-module native */

/** @module @web/core/utils/patch - Reversible monkey-patching for class prototypes and object properties */

/**
 *  @typedef {{
 *      originalProperties: Map<string, PropertyDescriptor | undefined>;
 *      skeleton: object;
 *      extensions: Set<object>;
 *  }} PatchDescription
 */

/** @type {WeakMap<object, PatchDescription>} */
const patchDescriptions = new WeakMap();

/**
 * Extension objects that are currently consumed by a live patch.
 *
 * ``patch()`` mutates its ``extension`` argument in place: it copies the
 * patched descriptors onto the target and re-parents ``extension`` onto the
 * previous skeleton (via ``Object.setPrototypeOf``) so the ``super`` keyword
 * resolves through the patch chain. That mutation makes each extension object
 * **single-use** — reusing one either corrupts the ``super`` chain of the first
 * target (when shared across two targets) or throws an opaque
 * ``TypeError: Cyclic __proto__ value`` (when applied twice to the same target).
 * This set lets ``patch()`` detect reuse up front and fail with a clear message.
 * Entries are cleared by the unpatch closure, which legitimately re-applies the
 * surviving extensions against a fresh description.
 *
 * @type {WeakSet<object>}
 */
const usedExtensions = new WeakSet();

/**
 * Create or get the patch description for the given `objToPatch`.
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
    // class A {}
    // isClassPrototype(A) === false
    // isClassPrototype(A.prototype) === true
    // isClassPrototype(new A()) === false
    // isClassPrototype({}) === false
    return (
        Object.hasOwn(objToPatch, "constructor") &&
        objToPatch.constructor?.prototype === objToPatch
    );
}

/**
 * Traverse the prototype chain to find a potential property.
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
 * Patch an object
 *
 * If the intent is to patch a class, don't forget to patch the prototype, unless
 * you want to patch static properties/methods.
 *
 * The `extension` object is **single-use**: `patch()` mutates it in place
 * (re-parenting it via `Object.setPrototypeOf` to wire up the `super` chain), so
 * the same extension object must not be passed to `patch()` more than once — not
 * to a second target, and not twice to the same target. Reuse throws a clear
 * error. Pass a fresh object literal / class for each `patch()` call.
 *
 * @template {object} T
 * @template {Partial<T>} U
 * @param {T} objToPatch The object to patch
 * @param {U} extension The object containing the patched properties
 * @returns {() => void} Returns an unpatch function
 */
export function patch(objToPatch, extension) {
    if (typeof extension === "string") {
        throw new Error(
            `Patch "${extension}": Second argument is not the patch name anymore, it should be the object containing the patched properties`,
        );
    }

    if (usedExtensions.has(extension)) {
        // The extension has already been consumed by a live patch. Reusing it
        // would corrupt the first patch's `super` chain (shared target) or throw
        // an opaque "Cyclic __proto__ value" (same target). Fail clearly instead.
        throw new Error(
            "patch(): extension object already used in a patch. Each patch() call " +
                "needs its own fresh extension object (it is mutated to build the `super` chain).",
        );
    }

    const description = getPatchDescription(objToPatch);
    description.extensions.add(extension);
    usedExtensions.add(extension);

    const properties = Object.getOwnPropertyDescriptors(extension);
    for (const [key, newProperty] of Object.entries(properties)) {
        const oldProperty = Object.getOwnPropertyDescriptor(objToPatch, key);
        if (oldProperty) {
            // Store the old property on the skeleton.
            Object.defineProperty(description.skeleton, key, oldProperty);
        }

        if (!description.originalProperties.has(key)) {
            // Keep a trace of original property (prop before first patch), useful for unpatching.
            description.originalProperties.set(key, oldProperty);
        }

        if (isClassPrototype(objToPatch)) {
            // A property is enumerable on POJO ({ prop: 1 }) but not on classes (class A {}).
            // Here, we only check if we patch a class prototype.
            newProperty.enumerable = false;
        }

        if (Boolean(newProperty.get) !== Boolean(newProperty.set)) {
            // get and set are defined together. If they are both defined
            // in the previous descriptor but only one in the new descriptor
            // then the other will be undefined so we need to apply the
            // previous descriptor in the new one.
            const ancestorProperty = findAncestorPropertyDescriptor(objToPatch, key);
            newProperty.get = newProperty.get ?? ancestorProperty?.get;
            newProperty.set = newProperty.set ?? ancestorProperty?.set;
        }

        // Replace the old property by the new one.
        Object.defineProperty(objToPatch, key, newProperty);
    }

    // Sets the current skeleton as the extension's prototype to make
    // `super` keyword working and then set extension as the new skeleton.
    description.skeleton = Object.setPrototypeOf(extension, description.skeleton);

    return () => {
        // Remove the description to start with a fresh base.
        patchDescriptions.delete(objToPatch);

        for (const [key, property] of description.originalProperties) {
            if (property) {
                // Restore the original property on the `objToPatch` object.
                Object.defineProperty(objToPatch, key, property);
            } else {
                // Or remove the property if it did not exist at first.
                delete (/** @type {Record<string, any>} */ (objToPatch)[key]);
            }
        }

        // Re-apply the patches without the current one.
        description.extensions.delete(extension);
        usedExtensions.delete(extension);
        for (const extension of description.extensions) {
            // Release each surviving extension so patch() can legitimately
            // re-consume it against the fresh description built above.
            usedExtensions.delete(extension);
            patch(objToPatch, extension);
        }
    };
}

/**
 * Diagnostic read accessor for the patch graph.
 *
 * Reports how an object has been patched so operators triaging a bug like
 * "form_controller saves twice" can answer "which addons override that
 * method, and in which order" without instrumenting the running session.
 *
 * Returns ``null`` for unpatched targets. For patched targets:
 * - ``extensions`` is the array of patch objects in original ``patch()``
 *   call order (the underlying ``Set`` preserves insertion order). The
 *   array is a fresh copy — mutating it never affects the patch graph.
 * - ``patchedKeys`` is the union of property keys any extension has
 *   touched, useful for "did *anyone* override ``save``?" queries.
 *
 * Note: this is a DevTools/test diagnostic helper — no production code
 * path calls it.
 *
 * @param {object} target Same object handed to ``patch()`` (class
 *   prototype, class constructor, or plain object).
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
