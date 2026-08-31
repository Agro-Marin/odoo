// @ts-check
/** @odoo-module native */

import { makeLazyFacade } from "@web/core/module_bridge";

/**
 * @param {() => Promise<any>} load resolves to the imported module
 * @param {Object} [options]
 * @param {(module: any) => any} [options.pick] the module member to face, if not the module
 * @param {(module: any) => any} [options.extra] a second member to face
 * @param {boolean} [options.constructable] the primary facade is called with `new`
 * @returns {{ facade: any, extraFacade: any, load: () => Promise<any> }}
 */
export function makeLazyLib(load, { pick, extra, constructable = false } = {}) {
    /** @type {any} */
    let value = null;
    /** @type {any} */
    let extraValue = null;
    /** @type {Promise<any> | null} */
    let loading = null;

    const facade = makeLazyFacade(() => value, { constructable });
    const extraFacade = extra ? makeLazyFacade(() => extraValue) : undefined;

    return {
        facade,
        extraFacade,
        load() {
            if (value) {
                return Promise.resolve(facade);
            }
            // A rejected load clears the memo so the next caller retries rather
            // than awaiting a promise that can only ever reject again.
            loading ??= load().then(
                (module) => {
                    value = pick ? pick(module) : module;
                    if (extra) {
                        extraValue = extra(module);
                    }
                    return facade;
                },
                (error) => {
                    loading = null;
                    throw error;
                },
            );
            return loading;
        },
    };
}
