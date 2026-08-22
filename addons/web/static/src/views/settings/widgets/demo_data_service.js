// @ts-check
/** @odoo-module native */

import { rpc } from "@web/core/network/rpc";
import { registry } from "@web/core/registry";
export const demoDataService = {
    /** @returns {Promise<{ isDemoDataActive: () => Promise<boolean> }>} */
    async start() {
        /** @type {Promise<boolean> | undefined} */
        let isDemoDataActiveProm;
        return {
            /**
             * @returns {Promise<boolean>}
             */
            isDemoDataActive() {
                isDemoDataActiveProm ??= rpc("/base_setup/demo_active").catch(
                    (/** @type {any} */ error) => {
                        isDemoDataActiveProm = undefined;
                        throw error;
                    },
                );
                return /** @type {Promise<boolean>} */ (isDemoDataActiveProm);
            },
        };
    },
};

registry.category("services").add("demo_data", demoDataService);
