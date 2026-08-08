// @ts-check

import { onServerStateChange } from "./mock_server_state.hoot.js";

/**
 * @param {string} name
 * @param {OdooModuleFactory} factory
 */
export function mockUserFactory(name, { fn }) {
    return (/** @type {any} */ requireModule, /** @type {any[]} */ ...args) => {
        const { session } = requireModule("@web/session");
        const userModule = /** @type {Function} */ (fn)(requireModule, ...args);

        onServerStateChange(userModule.user, () => userModule._makeUser(session));

        return userModule;
    };
}
