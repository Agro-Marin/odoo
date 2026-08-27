// @ts-check
/** @odoo-module native */

import { rpc } from "@web/core/network/rpc";
import { registry } from "@web/core/registry";

class DemoDataService {
    constructor() {
        /** @type {Promise<boolean> | undefined} */
        this.activeProm = undefined;
    }

    /**
     * @returns {Promise<boolean>}
     */
    isDemoDataActive() {
        this.activeProm ??= rpc("/base_setup/demo_active").catch(
            (/** @type {any} */ error) => {
                this.activeProm = undefined;
                throw error;
            },
        );
        return /** @type {Promise<boolean>} */ (this.activeProm);
    }
}

export const demoDataService = {
    /** @returns {Promise<DemoDataService>} */
    async start() {
        return new DemoDataService();
    },
};

registry.category("services").add("demo_data", demoDataService);
