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

// Re-export for backward compatibility — canonical location is @web/core/errors/uncaught_errors
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
                // Only log business-relevant errors: event/traceback are set by
                // one of the two listeners below, and skip if a handler opted
                // out of logging. For window "error" events the listener
                // already prevented the event synchronously (see below), so
                // handler opt-out is tracked via the shadowed preventDefault
                // (`logSuppressed`) instead of the event's canceled flag.
                if (!uncaughtError.event || !uncaughtError.traceback) {
                    return false;
                }
                if (uncaughtError.browserLogSuppressed) {
                    return !uncaughtError.logSuppressed;
                }
                return !uncaughtError.event.defaultPrevented;
            }
            // Unwrap to the deepest cause in the chain. Descend only while the
            // next `cause` is DEFINED: a non-Error reason (e.g. a rejected
            // promise with a string reason) is a legitimate original error and
            // must be surfaced, but a chain ending in `{ cause: undefined }`
            // must not hand handlers `originalError === undefined` — stop and
            // keep the last defined value instead.
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
                    // A crashing handler must not silence the original error or
                    // block later handlers. Log its failure briefly (the original
                    // traceback is logged once by the fallback below) and continue.
                    console.error(
                        `@web/services/error_service: handler "${name}" failed with "${
                            e?.cause || e
                        }" while trying to handle:\n${uncaughtError.cause || uncaughtError.message}`,
                    );
                }
            }
            if (shouldLogError()) {
                // Log the full traceback instead of letting the browser log the incomplete one
                uncaughtError.event.preventDefault();
                console.error(uncaughtError.traceback);
            }
        }

        // Named handlers (not inline) so ``destroy()`` below can detach them:
        // an env that starts this service and is later torn down (notably every
        // env spun up across a test suite) would otherwise leak both window
        // listeners, each pinning the dead env — the same fix the sibling
        // name/slow_rpc services already carry.
        const onError = async (ev) => {
            const { colno, error, filename, lineno, message } = ev;
            // Never surface this ResizeObserver error to the user: it just means the
            // browser deferred notifications a frame to prevent an infinite loop —
            // expected behavior, though worth tracking down the trigger sites.
            // https://trackjs.com/javascript-errors/resizeobserver-loop-completed-with-undelivered-notifications/
            const resizeObserverError =
                "ResizeObserver loop completed with undelivered notifications.";
            if (!(error instanceof Error) && message === resizeObserverError) {
                ev.preventDefault();
                return;
            }
            const isRedactedError = !filename && !lineno && !colno;
            let isThirdPartyScriptError = isRedactedError;
            if (!isRedactedError && isBrowserFirefox() && filename) {
                // Firefox doesn't hide details of errors occurring in third-party scripts, check origin explicitly.
                try {
                    isThirdPartyScriptError =
                        new URL(filename).origin !== window.location.origin;
                } catch {
                    // filename is not a valid URL (inline script, eval, etc.) — not third-party
                }
            }
            // Don't display error dialogs for third party script errors unless we are in debug mode
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
                    // The browser prints its own (partial) report for an
                    // uncaught error unless preventDefault runs synchronously
                    // during dispatch — after the await below it would be a
                    // no-op and the error would hit the console twice. Prevent
                    // now (unless another listener already claimed the event),
                    // and shadow preventDefault so handlers that call it to
                    // opt out of the traceback log (e.g. website's
                    // beforeunload suppression) keep working. Rejection events
                    // don't need this: their report is deferred past the
                    // microtask queue, so the late preventDefault is honored.
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
                // https://developer.mozilla.org/en-US/docs/Web/API/HTMLElement/error_event
                // The error Event doesn't bubble. We sometimes reject a promise with the
                // Event from an HTMLElement's "error" handler; if it isn't wrapped in an
                // actual Error, there's nothing more to do than the spec requires.
                if (!error.bubbles) {
                    ev.preventDefault();
                    return;
                }
                // If the error Event does bubble, build a meaningful message.
                let message;
                if (error.target) {
                    message = `${HTMLElementLoadingError.message}: ${error.target.nodeName}`;
                }
                error = new HTMLElementLoadingError(message, error);
            }

            let traceback;
            if (isBrowserChrome() && ev instanceof CustomEvent && error === undefined) {
                // Ad-hoc fix for the Honey Paypal extension bug: it throws a CustomEvent
                // instead of the spec'd PromiseRejectionEvent (Chrome doesn't sandbox
                // extensions enough to keep this out of the page). Ignore unless debugging.
                // https://developer.mozilla.org/en-US/docs/Web/API/Window/unhandledrejection_event
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
