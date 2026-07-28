// @ts-check
/** @odoo-module native */

/** @module @web/services/error_service - Global error/rejection interceptor with UncaughtError classification and handler pipeline */

import { browser } from "@web/core/browser/browser";
import { isBrowserChrome, isBrowserFirefox } from "@web/core/browser/feature_detection";
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

/** Error raised when an HTML element (img, script, iframe) fails to load. */
class HTMLElementLoadingError extends Error {
    static message = "Error loading an HTML Element";
    /**
     * @param {string} [message]
     * @param {Event} [event] - the DOM error event
     */
    constructor(message = HTMLElementLoadingError.message, event) {
        super(message);
        /** @type {Event | undefined} */
        this.event = event;
    }
}

/**
 * Global error handling service. Listens for uncaught errors and unhandled
 * promise rejections, classifies them, and dispatches to registered error handlers.
 */
export const errorService = {
    /**
     * @param {import("@web/env").OdooEnv} env
     */
    start(env) {
        /**
         * Dispatch an uncaught error to all registered error handlers.
         * @param {UncaughtError} uncaughtError
         */
        function handleError(/** @type {any} */ uncaughtError) {
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
                    if (handler(env, uncaughtError, originalError)) {
                        break;
                    }
                } catch (e) {
                    console.error(
                        `@web/services/error_service: handler "${name}" failed with "${
                            e?.cause || e
                        }" while trying to handle:\n${uncaughtError.cause || uncaughtError.message}`,
                    );
                }
            }
            if (shouldLogError()) {
                uncaughtError.event.preventDefault();
                console.error(uncaughtError.traceback);
            }
        }

        const onError = async (ev) => {
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
                } catch {
                    // filename is not a valid URL (inline script, eval, etc.) — not third-party
                }
            }
            if (isThirdPartyScriptError && !env.debug) {
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
                    if (!ev.defaultPrevented) {
                        ev.preventDefault();
                        /** @type {any} */ (uncaughtError).browserLogSuppressed = true;
                        try {
                            Object.defineProperty(ev, "preventDefault", {
                                configurable: true,
                                value: () => {
                                    /** @type {any} */ (uncaughtError).logSuppressed =
                                        true;
                                },
                            });
                        } catch {
                            // Instrumented event (e.g. hoot pins a
                            // non-configurable preventDefault): handler
                            // opt-out tracking is lost, which only affects
                            // console verbosity.
                        }
                    }
                    const annotated = env.debug?.includes("assets");
                    await completeUncaughtError(uncaughtError, error, annotated);
                }
            }
            uncaughtError.cause = error;
            handleError(uncaughtError);
        };
        browser.addEventListener("error", onError);

        const onUnhandledRejection = async (ev) => {
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
                if (!env.debug) {
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
            // Suppress the browser's own log ONLY when this service will print
            // a traceback itself, i.e. when one is already set or when
            // `completeUncaughtError` below is going to set one (it runs only
            // for real Errors). Suppressing unconditionally silences a
            // `Promise.reject("string")` entirely: shouldLogError() bails on
            // the null traceback, so neither the browser nor Odoo reports it.
            //
            // It must also happen BEFORE the awaits below: preventDefault() on
            // an already-dispatched event is a no-op, which is why the deferred
            // call in shouldLogError() never suppressed anything and every
            // Error rejection was logged twice. Mirrors the "error" path.
            const willReportTraceback = error instanceof Error || Boolean(traceback);
            if (willReportTraceback && !ev.defaultPrevented) {
                ev.preventDefault();
                /** @type {any} */ (uncaughtError).browserLogSuppressed = true;
                try {
                    // Keep a handler's later preventDefault() meaningful as an
                    // opt-out of Odoo's own log, now that the real one has
                    // already fired.
                    Object.defineProperty(ev, "preventDefault", {
                        configurable: true,
                        value: () => {
                            /** @type {any} */ (uncaughtError).logSuppressed = true;
                        },
                    });
                } catch {
                    // Instrumented event: opt-out tracking is lost, which only
                    // affects console verbosity.
                }
            }
            if (error instanceof Error) {
                /** @type {any} */ (error).errorEvent = ev;
                const annotated = env.debug?.includes("assets");
                await completeUncaughtError(uncaughtError, error, annotated);
            }
            uncaughtError.cause = error;
            handleError(uncaughtError);
        };
        browser.addEventListener("unhandledrejection", onUnhandledRejection);

        return {
            destroy() {
                browser.removeEventListener("error", onError);
                browser.removeEventListener("unhandledrejection", onUnhandledRejection);
            },
        };
    },
};

registry.category("services").add("error", errorService, { sequence: 1 });
