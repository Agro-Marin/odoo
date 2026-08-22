// @ts-check
/** @odoo-module native */

import { rpc } from "@web/core/network/rpc";
import { registry } from "@web/core/registry";
export const userInviteService = {
    /** @returns {Promise<{ fetchData: (reload?: boolean) => Promise<Record<string, any>> }>} */
    async start() {
        /** @type {Promise<Record<string, any>> | undefined} */
        let dataProm;
        return {
            /**
             * @param {boolean} [reload=false]
             * @returns {Promise<Record<string, any>>}
             */
            fetchData(reload = false) {
                if (!dataProm || reload) {
                    const prom = rpc("/base_setup/data").catch(
                        (/** @type {any} */ error) => {
                            if (dataProm === prom) {
                                dataProm = undefined;
                            }
                            throw error;
                        },
                    );
                    dataProm = prom;
                }
                return /** @type {Promise<Record<string, any>>} */ (dataProm);
            },
        };
    },
};

registry.category("services").add("user_invite", userInviteService);
