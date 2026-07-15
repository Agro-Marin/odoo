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
 * Weak enumeration of every object ever handed to ``patch()`` as a target.
 *
 * ``patchDescriptions`` is a WeakMap, which is the right lifetime model but
 * makes the patch graph non-enumerable — diagnostics like ``patchInfo`` can
 * only answer questions about a target the caller already holds. This set of
 * ``WeakRef``s adds enumeration for {@link getPatchedTargets} without
 * extending any target's lifetime (dead refs are pruned on read).
 * ``enumerableTargets`` (a WeakSet) only dedupes: one ref per target ever.
 *
 * @type {Set<WeakRef<object>>}
 */
const patchedTargetRefs = new Set();

/** @type {WeakSet<object>} */
const enumerableTargets = new WeakSet();

/**
 * Keys each extension object *declared* when it was first handed to
 * ``patch()``. Recorded before the patch is applied because ``patch()``
 * mutates extension objects afterwards: when a later patch overrides key
 * ``K``, the previous descriptor of ``K`` is copied onto the current
 * skeleton — which is the *previous extension object*. Own-key inspection of
 * an extension therefore over-reports (it includes such skeleton copies);
 * this map preserves the honest set for {@link patchDeclaredKeys}. Recorded
 * once per extension: the unpatch closure legitimately re-applies surviving
 * extensions, whose own keys may by then include skeleton copies.
 *
 * @type {WeakMap<object, string[]>}
 */
const extensionDeclaredKeys = new WeakMap();

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
        // Reusing an extension would corrupt the `super` chain (shared target)
        // or throw an opaque "Cyclic __proto__" error (same target) — see
        // `usedExtensions` above. Fail clearly instead.
        throw new Error(
            "patch(): extension object already used in a patch. Each patch() call " +
                "needs its own fresh extension object (it is mutated to build the `super` chain).",
        );
    }

    const description = getPatchDescription(objToPatch);
    description.extensions.add(extension);
    usedExtensions.add(extension);
    if (!enumerableTargets.has(objToPatch)) {
        enumerableTargets.add(objToPatch);
        patchedTargetRefs.add(new WeakRef(objToPatch));
    }

    const properties = Object.getOwnPropertyDescriptors(extension);
    if (!extensionDeclaredKeys.has(extension)) {
        extensionDeclaredKeys.set(extension, Object.keys(properties));
    }
    for (const [key, newProperty] of Object.entries(properties)) {
        const oldProperty = Object.getOwnPropertyDescriptor(objToPatch, key);
        if (oldProperty) {
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
            // get/set are defined together; if only one is present on the
            // new descriptor, inherit the other from the previous one so it
            // isn't clobbered to undefined.
            const ancestorProperty = findAncestorPropertyDescriptor(objToPatch, key);
            newProperty.get = newProperty.get ?? ancestorProperty?.get;
            newProperty.set = newProperty.set ?? ancestorProperty?.set;
        }

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
                Object.defineProperty(objToPatch, key, property);
            } else {
                // `property` is undefined when the key didn't exist before patching.
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
 * Diagnostic read accessor for the patch graph: reports how an object has
 * been patched so operators triaging a bug like "form_controller saves
 * twice" can answer "which addons override that method, and in which
 * order" without instrumenting the running session. DevTools/test helper
 * only — no production code path calls it.
 *
 * Returns ``null`` for unpatched targets. ``extensions`` is the array of
 * patch objects in ``patch()`` call order (a fresh copy — mutating it never
 * affects the patch graph); ``patchedKeys`` is the union of keys any
 * extension has touched.
 *
 * @param {object} target Same object handed to ``patch()`` (class
 *   prototype, class constructor, or plain object).
 * @returns {{ extensions: object[], patchedKeys: string[] } | null}
 */
/**
 * Diagnostic companion to ``patchInfo``: enumerate every object that
 * currently has at least one live patch. Backed by weak references, so it
 * never keeps a target alive; targets whose patches were all reverted (or
 * that were garbage-collected) are skipped. DevTools/test helper only — no
 * production code path calls it.
 *
 * @returns {object[]} the currently patched targets (fresh array)
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
 * The keys an extension object declared when it was passed to ``patch()``.
 *
 * Prefer this over inspecting the extension's own keys: ``patch()`` re-uses
 * extension objects as skeletons of the ``super`` chain and copies previous
 * descriptors onto them, so own-key inspection over-reports (see
 * ``extensionDeclaredKeys``). Returns ``null`` for objects never used as a
 * ``patch()`` extension. DevTools/test helper only.
 *
 * @param {object} extension An extension object as passed to ``patch()``
 * @returns {string[] | null} fresh copy of the declared keys
 */
export function patchDeclaredKeys(extension) {
    const keys = extensionDeclaredKeys.get(extension);
    return keys ? [...keys] : null;
}

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
