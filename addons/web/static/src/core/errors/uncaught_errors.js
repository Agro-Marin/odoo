// @ts-check
/** @odoo-module native */

import { getErrorTechnicalName } from "./error_utils.js";

export class UncaughtError extends Error {
    /** @param {string} message */
    constructor(message) {
        super(message);
        this.name = getErrorTechnicalName(this);
        /** @type {string | null} */
        this.traceback = null;
        /**
         * The browser event this error was raised from, when there is one.
         * Declared on the base because every handler reads it the same way -- to
         * suppress the default logging, or to name the host that served the
         * failing script. It used to be stamped onto the instance through an
         * `any` cast at two of the three construction sites, which left
         * `ThirdPartyScriptError` without one and its dialog without a host.
         *
         * @type {Event | PromiseRejectionEvent | null}
         */
        this.event = null;
    }
}

export class UncaughtClientError extends UncaughtError {
    /** @param {string} [message] */
    constructor(message = "Uncaught Javascript Error") {
        super(message);
    }
}

export class UncaughtPromiseError extends UncaughtError {
    /** @param {string} [message] */
    constructor(message = "Uncaught Promise") {
        super(message);
    }
}

export class ThirdPartyScriptError extends UncaughtError {
    /** @param {string} [message] */
    constructor(message = "Third-Party Script Error") {
        super(message);
    }
}
