// @ts-check
/** @odoo-module native */
import { onMounted, onPatched, onWillUnmount } from "@odoo/owl";

/**
 * @template {unknown[]} T
 * @param {(...dependencies: T) => void | (() => void)} effect
 * @param {() => T} [computeDependencies]
 */
export function useLayoutEffect(
    effect,
    computeDependencies = () => /** @type {T} */ (/** @type {unknown} */ ([NaN])),
) {
    /** @type {void | (() => void)} */
    let cleanup;
    /** @type {T} */
    let dependencies;
    onMounted(() => {
        dependencies = computeDependencies();
        cleanup = effect(...dependencies);
    });
    onPatched(() => {
        const newDeps = computeDependencies();
        if (newDeps.some((value, index) => value !== dependencies[index])) {
            dependencies = newDeps;
            if (cleanup) {
                cleanup();
            }
            cleanup = effect(...dependencies);
        }
    });
    onWillUnmount(() => cleanup && cleanup());
}
