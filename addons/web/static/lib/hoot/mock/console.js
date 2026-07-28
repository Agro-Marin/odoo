/** @odoo-module */

import { MockEventTarget } from "../hoot_utils.js";
import { logger } from "../core/logger.js";

const {
    console,
    Object: { keys: $keys },
} = globalThis;

const DISPATCHING_METHODS = ["error", "trace", "warn"];

export class MockConsole extends MockEventTarget {
    static {
        for (const fnName of $keys(console)) {
            if (DISPATCHING_METHODS.includes(fnName)) {
                const fn = logger[fnName];
                this.prototype[fnName] = function (...args) {
                    this.dispatchEvent(new CustomEvent(fnName, { detail: args }));
                    return fn.apply(this, arguments);
                };
            } else {
                this.prototype[fnName] = console[fnName];
            }
        }
    }
}
