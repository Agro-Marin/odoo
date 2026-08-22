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
        /** @type {PromiseRejectionEvent | null} */
        this.unhandledRejectionEvent = null;
    }
}

export class ThirdPartyScriptError extends UncaughtError {
    /** @param {string} [message] */
    constructor(message = "Third-Party Script Error") {
        super(message);
    }
}
