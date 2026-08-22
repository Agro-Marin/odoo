// @ts-check
/** @odoo-module native */

import { registry } from "@web/core/registry";

/**
 * Per-model allowlist of QWeb expressions a non-template-editor may insert into
 * a mail template.
 *
 * This lives in `mail` because the model method it calls does:
 * `mail_allowed_qweb_expressions` is declared in `mail/models/base.py`, so a
 * database without `mail` answers the call with
 * `AttributeError: The method '<model>.mail_allowed_qweb_expressions' does not
 * exist`. It used to be registered from `web/core`, which depends on `base`
 * alone -- the service was therefore present, and faulting, on every install
 * that had `html_editor` (auto-installed) but not `mail`.
 *
 * Consumers in `web` must treat this service as optional and skip the allowlist
 * check when it is absent; see `dynamic_placeholder_popover.js`.
 *
 * @type {{
 * dependencies: string[],
 * async: boolean,
 * start: (env: any, deps: any) => (resModel: string) => Promise<string[]>,
 * }}
 */
export const allowedQwebExpressionsService = {
    dependencies: ["orm"],
    async: true,
    start(env, { orm }) {
        /** @type {Map<string, Promise<string[]>>} */
        const cache = new Map();
        return (resModel) => {
            const cached = cache.get(resModel);
            if (cached) {
                return cached;
            }
            const prom = orm
                .call(resModel, "mail_allowed_qweb_expressions")
                .catch((/** @type {unknown} */ e) => {
                    cache.delete(resModel);
                    return Promise.reject(e);
                });
            cache.set(resModel, prom);
            return prom;
        };
    },
};

registry
    .category("services")
    .add("allowed_qweb_expressions", allowedQwebExpressionsService);
