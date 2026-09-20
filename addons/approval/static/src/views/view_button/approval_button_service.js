/** @odoo-module native */
import { browser } from "@web/core/browser/browser";
import { registry } from "@web/core/registry";

import { trace } from "../../common/approval_trace.js";

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
            const started = browser.performance.now();
            orm.silent
                .call("approval.binding", "get_button_approvals", [
                    batch.map(({ spec }) => spec),
                ])
                .then(
                    (results) => {
                        trace.event("service", "flushed", {
                            specs: batch.length,
                            ms: browser.performance.now() - started,
                            results: results.length,
                        });
                        batch.forEach(({ resolve }, index) => resolve(results[index]));
                    },
                    (error) => {
                        // Every queued button fails open on this, so it is the one
                        // place that knows the gates were never actually consulted.
                        trace.note("service", "flush_rejected", {
                            specs: batch.length,
                            ms: browser.performance.now() - started,
                            error: error?.name || "Error",
                        });
                        batch.forEach(({ reject }) => reject(error));
                    },
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
