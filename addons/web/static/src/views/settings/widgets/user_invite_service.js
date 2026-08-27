// @ts-check
/** @odoo-module native */

import { rpc } from "@web/core/network/rpc";
import { registry } from "@web/core/registry";

class UserInviteService {
    constructor() {
        /** @type {Promise<Record<string, any>> | undefined} */
        this.dataProm = undefined;
    }

    /**
     * @param {boolean} [reload=false]
     * @returns {Promise<Record<string, any>>}
     */
    fetchData(reload = false) {
        if (!this.dataProm || reload) {
            const prom = rpc("/base_setup/data").catch((/** @type {any} */ error) => {
                if (this.dataProm === prom) {
                    this.dataProm = undefined;
                }
                throw error;
            });
            this.dataProm = prom;
        }
        return /** @type {Promise<Record<string, any>>} */ (this.dataProm);
    }
}

export const userInviteService = {
    /** @returns {Promise<UserInviteService>} */
    async start() {
        return new UserInviteService();
    },
};

registry.category("services").add("user_invite", userInviteService);
