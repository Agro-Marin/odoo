/** @odoo-module native */
import { registry } from "@web/core/registry";

/**
 * Collects the specs asked in one tick and answers them with one call, so a form
 * with several gated buttons costs one round trip.
 */
export const approvalButtonService = {
    dependencies: ["orm"],
    start(env, { orm }) {
        let queue = [];

        function flush() {
            const batch = queue;
            queue = [];
            orm.silent
                .call("approval.binding", "get_button_approvals", [
                    batch.map(({ spec }) => spec),
                ])
                .then(
                    (results) =>
                        batch.forEach(({ resolve }, index) => resolve(results[index])),
                    (error) => batch.forEach(({ reject }) => reject(error)),
                );
        }

        return {
            load(spec) {
                return new Promise((resolve, reject) => {
                    if (!queue.length) {
                        Promise.resolve().then(flush);
                    }
                    queue.push({ spec, resolve, reject });
                });
            },
        };
    },
};

registry.category("services").add("approval_button", approvalButtonService);
