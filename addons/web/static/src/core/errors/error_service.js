// @ts-check
/** @odoo-module native */

import { browser } from "@web/core/browser/browser";
import { isBrowserChrome, isBrowserFirefox } from "@web/core/browser/feature_detection";
import { reportJsError } from "@web/core/errors/error_beacon";
import { completeUncaughtError } from "@web/core/errors/error_utils";
import {
    ThirdPartyScriptError,
    UncaughtClientError,
    UncaughtError,
    UncaughtPromiseError,
} from "@web/core/errors/uncaught_errors";
import { registry } from "@web/core/registry";

export {
    ThirdPartyScriptError,
    UncaughtClientError,
    UncaughtError,
    UncaughtPromiseError,
};

class HTMLElementLoadingError extends Error {
    static message = "Error loading an HTML Element";
    /**
     * @param {string} [message]
     * @param {Event} [event]
     */
    constructor(message = HTMLElementLoadingError.message, event) {
        super(message);
        /** @type {Event | undefined} */
        this.event = event;
    }
}

/**
 * @param {any} ev
 * @param {any} uncaughtError
 */
function assumeBrowserLogging(ev, uncaughtError) {
    if (ev.defaultPrevented) {
        return;
    }
    ev.preventDefault();
    uncaughtError.browserLogSuppressed = true;
    try {
        Object.defineProperty(ev, "preventDefault", {
            configurable: true,
            value: () => {
                uncaughtError.logSuppressed = true;
            },
        });
    } catch {}
}

class ErrorService {
    /**
     * @param {import("@web/env").OdooEnv} env
     */
    constructor(env) {
        this.env = env;
        this._onError = (/** @type {any} */ ev) => this.onError(ev);
        this._onUnhandledRejection = (/** @type {any} */ ev) =>
            this.onUnhandledRejection(ev);
        browser.addEventListener("error", this._onError);
        browser.addEventListener("unhandledrejection", this._onUnhandledRejection);
    }

    handleError(/** @type {any} */ uncaughtError) {
        function shouldLogError() {
            if (!uncaughtError.event || !uncaughtError.traceback) {
                return false;
            }
            if (uncaughtError.browserLogSuppressed) {
                return !uncaughtError.logSuppressed;
            }
            return !uncaughtError.event.defaultPrevented;
        }
        let originalError = uncaughtError;
        const seen = new Set();
        while (
            originalError instanceof Error &&
            originalError.cause != null &&
            !seen.has(originalError)
        ) {
            seen.add(originalError);
            originalError = originalError.cause;
        }
        for (const [name, handler] of registry
            .category("error_handlers")
            .getEntries()) {
            try {
                if (handler(this.env, uncaughtError, originalError)) {
                    break;
                }
            } catch (e) {
                console.error(
                    `@web/core/errors/error_service: handler "${name}" failed with "${
                        e?.cause || e
                    }" while trying to handle:\n${uncaughtError.cause || uncaughtError.message}`,
                );
            }
        }
        if (shouldLogError()) {
            uncaughtError.event.preventDefault();
            console.error(uncaughtError.traceback);
            reportJsError({
                kind: uncaughtError.event.type,
                message: String(
                    originalError?.message ??
                        originalError ??
                        uncaughtError.message ??
                        "",
                ),
                filename: uncaughtError.event.filename ?? "",
                line: uncaughtError.event.lineno ?? 0,
                col: uncaughtError.event.colno ?? 0,
                stack: uncaughtError.traceback ?? "",
            });
        }
    }

    async onError(ev) {
        const { colno, error, filename, lineno, message } = ev;
        const resizeObserverError =
            "ResizeObserver loop completed with undelivered notifications.";
        if (!(error instanceof Error) && message === resizeObserverError) {
            ev.preventDefault();
            return;
        }
        const isRedactedError = !filename && !lineno && !colno;
        let isThirdPartyScriptError = isRedactedError;
        if (!isRedactedError && isBrowserFirefox() && filename) {
            try {
                isThirdPartyScriptError =
                    new URL(filename).origin !== browser.location.origin;
            } catch {}
        }
        if (isThirdPartyScriptError && !this.env.debug) {
            return;
        }
        let uncaughtError;
        if (isRedactedError) {
            uncaughtError = new ThirdPartyScriptError();
            uncaughtError.traceback =
                `An error whose details cannot be accessed by the Odoo framework has occurred.\n` +
                `The error probably originates from a JavaScript file served from a different origin.\n` +
                `The full error is available in the browser console.`;
        } else {
            uncaughtError = new UncaughtClientError();
            /** @type {any} */ (uncaughtError).event = ev;
            if (error instanceof Error) {
                /** @type {any} */ (error).errorEvent = ev;
                assumeBrowserLogging(ev, uncaughtError);
                const annotated = this.env.debug?.includes("assets");
                await completeUncaughtError(uncaughtError, error, annotated);
            }
        }
        uncaughtError.cause = error;
        this.handleError(uncaughtError);
    }

    async onUnhandledRejection(ev) {
        let error = ev.reason;

        if (error && error.type === "error" && "eventPhase" in error) {
            if (!error.bubbles) {
                ev.preventDefault();
                return;
            }
            let message;
            if (error.target) {
                message = `${HTMLElementLoadingError.message}: ${error.target.nodeName}`;
            }
            error = new HTMLElementLoadingError(message, error);
        }

        let traceback;
        if (isBrowserChrome() && ev instanceof CustomEvent && error === undefined) {
            if (!this.env.debug) {
                return;
            }
            traceback =
                `Uncaught unknown Error\n` +
                `An unknown error occured. This may be due to a Chrome extension meddling with Odoo.\n` +
                `(Opening your browser console might give you a hint on the error.)`;
        }
        const uncaughtError = new UncaughtPromiseError();
        uncaughtError.unhandledRejectionEvent = ev;
        /** @type {any} */ (uncaughtError).event = ev;
        uncaughtError.traceback = traceback ?? null;
        const willReportTraceback = error instanceof Error || Boolean(traceback);
        if (willReportTraceback) {
            assumeBrowserLogging(ev, uncaughtError);
        }
        if (error instanceof Error) {
            /** @type {any} */ (error).errorEvent = ev;
            const annotated = this.env.debug?.includes("assets");
            await completeUncaughtError(uncaughtError, error, annotated);
        }
        uncaughtError.cause = error;
        this.handleError(uncaughtError);
    }

    destroy() {
        browser.removeEventListener("error", this._onError);
        browser.removeEventListener("unhandledrejection", this._onUnhandledRejection);
    }
}

const errorService = {
    /**
     * @param {import("@web/env").OdooEnv} env
     * @returns {ErrorService}
     */
    start(env) {
        return new ErrorService(env);
    },
};

registry.category("services").add("error", errorService, { sequence: 1 });
