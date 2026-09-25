// @ts-check
/** @odoo-module native */
import { onMounted, onPatched, onWillUnmount } from "@odoo/owl";

/**
 * @param {(...dependencies: any[]) => void | (() => void)} effect
 * @param {() => unknown[]} [computeDependencies]
 */
export function useLayoutEffect(effect, computeDependencies = () => [NaN]) {
    /** @type {void | (() => void)} */
    let cleanup;
    /** @type {unknown[]} */
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
