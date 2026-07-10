// @ts-check
/** @odoo-module native */

/** @module @web/core/utils/macro - Step-based macro engine for automated UI interaction sequences */

import { validate } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { delay } from "@web/core/utils/concurrency";
import { isVisible } from "@web/core/utils/dom/ui";

const macroSchema = {
    name: { type: String, optional: true },
    timeout: { type: Number, optional: true },
    steps: {
        type: Array,
        element: {
            type: Object,
            shape: {
                // `action` is always CALLED (`action(trigger)`); accepting only a
                // function (not `[Function, String]`) fails fast on a bad step.
                action: { type: Function, optional: true },
                timeout: { type: Number, optional: true },
                trigger: { type: [Function, String], optional: true },
            },
            validate: (/** @type {any} */ step) => step.action || step.trigger,
        },
    },
    onComplete: { type: Function, optional: true },
    onStep: { type: Function, optional: true },
    onError: { type: Function, optional: true },
};

class MacroError extends Error {
    /**
     * @param {string} type
     * @param {string} message
     * @param {ErrorOptions} [options]
     */
    constructor(type, message, options) {
        super(message, options);
        this.type = type;
    }
}

/**
 * @param {any} trigger
 * @param {any} action
 */
async function performAction(trigger, action) {
    if (!action) {
        return;
    }
    try {
        return await action(trigger);
    } catch (error) {
        throw new MacroError(
            "Action",
            error.stack || `ERROR during perform action: ${error.message}`,
            { cause: error },
        );
    }
}

/**
 * @param {Function | string} [trigger]
 * @param {AbortSignal} [signal]
 */
async function waitForTrigger(trigger, signal) {
    if (!trigger) {
        return;
    }
    try {
        await delay(50);
        return await waitUntil(
            () => {
                if (typeof trigger === "function") {
                    return trigger();
                } else if (typeof trigger === "string") {
                    const triggerEl = document.querySelector(trigger);
                    return isVisible(triggerEl) && triggerEl;
                }
            },
            { signal },
        );
    } catch (error) {
        throw new MacroError(
            "Trigger",
            `ERROR during find trigger:\n${error.message}`,
            {
                cause: error,
            },
        );
    }
}

/**
 * Wait until a predicate returns a truthy value, polling via requestAnimationFrame.
 *
 * @template T
 * @param {() => T} predicate
 * @param {{ signal?: AbortSignal }} [options] abort the polling loop through
 *  `signal` (the returned promise then rejects with an "AbortError")
 * @returns {Promise<T>}
 */
export async function waitUntil(predicate, { signal } = {}) {
    if (signal?.aborted) {
        throw new DOMException("waitUntil has been aborted", "AbortError");
    }
    const result = predicate();
    if (result) {
        return Promise.resolve(result);
    }
    /** @type {number} */
    let handle;
    return new Promise((resolve, reject) => {
        signal?.addEventListener(
            "abort",
            () => reject(new DOMException("waitUntil has been aborted", "AbortError")),
            { once: true },
        );
        const runCheck = () => {
            const result = predicate();
            if (result) {
                resolve(result);
            }
            handle = browser.requestAnimationFrame(runCheck);
        };
        handle = browser.requestAnimationFrame(runCheck);
    }).finally(() => {
        browser.cancelAnimationFrame(handle);
    });
}

/**
 * @typedef {{ action?: Function, timeout?: number, trigger?: Function | string }} MacroStep
 */

export class Macro {
    /**
     * Sentinel a step `action` can return to halt the macro without firing
     * `onComplete`/`onError` (e.g. a step navigates away and later steps must
     * not run). Prefer this over an ad-hoc truthy value (deprecated).
     *
     * @type {symbol}
     */
    static STOP = Symbol("Macro.STOP");

    currentIndex = 0;
    isComplete = false;
    /** @type {string | undefined} */
    name = undefined;
    /** @type {number | undefined} */
    timeout = undefined;
    /** @type {MacroStep[]} */
    steps = [];
    /** @type {AbortController | undefined} */
    abortController;
    /** @type {Function} */
    onComplete = () => {};
    /** @type {Function} */
    onStep = () => {};
    /** @type {Function} */
    onError = () => {};
    /**
     * @param {{ name?: string, timeout?: number, steps?: MacroStep[], onComplete?: Function, onStep?: Function, onError?: Function }} descr
     */
    constructor(descr) {
        try {
            validate(descr, macroSchema);
        } catch (error) {
            throw new Error(
                `Error in schema for Macro ${JSON.stringify(descr, null, 4)}\n${error.message}`,
                { cause: error },
            );
        }
        Object.assign(this, descr);
        this.onComplete ??= () => {};
        this.onStep ??= () => {};
        this.onError ??= (
            /** @type {Error} */ error,
            /** @type {MacroStep} */ step,
            /** @type {number} */ index,
        ) => {
            console.error(error.message, step, index);
        };
    }

    async start() {
        await this.advance();
    }

    async advance() {
        if (this.isComplete || this.currentIndex >= this.steps.length) {
            this.stop();
            return;
        }
        try {
            const step = this.steps[this.currentIndex];
            const timeoutDelay = step.timeout || this.timeout || 10000;
            const abortController = new AbortController();
            this.abortController = abortController;
            const executeStep = async () => {
                const trigger = await waitForTrigger(
                    step.trigger,
                    abortController.signal,
                );
                const result = await performAction(trigger, step.action);
                await this.onStep({ step, trigger, index: this.currentIndex });
                return result;
            };
            const launchTimer = async () => {
                await delay(timeoutDelay);
                // Cancel the trigger polling loop, which would otherwise keep
                // running (and leak) after losing the race.
                abortController.abort();
                throw new MacroError(
                    "Timeout",
                    `TIMEOUT step failed to complete within ${timeoutDelay} ms.`,
                );
            };
            const stepPromise = executeStep();
            // The race may settle with the timer's rejection: keep the losing
            // step promise's abort rejection from being reported as unhandled.
            stepPromise.catch(() => {});
            // Falsy result → proceed to next step. `Macro.STOP` (or a legacy
            // truthy value) halts without onComplete/onError.
            const actionResult = await Promise.race([stepPromise, launchTimer()]);
            if (actionResult) {
                if (actionResult !== Macro.STOP) {
                    // Backward-compat: some callers (e.g. web_tour) still return an
                    // ad-hoc truthy value to halt; keep working but nudge toward Macro.STOP.
                    console.warn(
                        "Macro: a step action returned a truthy value to halt the macro. " +
                            "Return `Macro.STOP` instead; other truthy return values are deprecated.",
                    );
                }
                this.stop();
                return;
            }
        } catch (error) {
            this.stop(error);
            return;
        }
        this.currentIndex++;
        await this.advance();
    }

    /**
     * @param {Error} [error]
     */
    stop(error) {
        if (this.isComplete) {
            return;
        }
        this.isComplete = true;
        this.abortController?.abort();
        if (error) {
            const step = this.steps[this.currentIndex];
            this.onError({ error, step, index: this.currentIndex });
        } else if (this.currentIndex === this.steps.length) {
            this.onComplete();
        }
    }
}

export class MacroMutationObserver {
    observerOptions = {
        attributes: true,
        childList: true,
        subtree: true,
        characterData: true,
    };
    /**
     * @param {Function} callback
     */
    constructor(callback) {
        this.callback = callback;
        // Every listener is registered with this controller's signal so
        // disconnect() removes them all (previously the iframe "load" listeners leaked).
        this.abortController = new AbortController();
        /** @type {WeakSet<HTMLIFrameElement>} Guard against double-adding iframe "load" listeners. */
        this.observedIframes = new WeakSet();
        /** @type {WeakSet<Document>} Guard against double-adding contentDocument "load" listeners. */
        this.observedContentDocuments = new WeakSet();
        this.observer = new MutationObserver((mutationList, observer) => {
            callback(mutationList);
            mutationList.forEach((mutationRecord) =>
                Array.from(mutationRecord.addedNodes).forEach((node) => {
                    /** @type {HTMLIFrameElement[]} */
                    let iframes = [];
                    if (
                        String(/** @type {Element} */ (node).tagName).toLowerCase() ===
                        "iframe"
                    ) {
                        iframes = [/** @type {HTMLIFrameElement} */ (node)];
                    } else if (node instanceof HTMLElement) {
                        iframes = Array.from(node.querySelectorAll("iframe"));
                    }
                    iframes.forEach((iframeEl) =>
                        this.observeIframe(iframeEl, observer, () => callback()),
                    );
                    this.findAllShadowRoots(node).forEach((shadowRoot) =>
                        observer.observe(shadowRoot, this.observerOptions),
                    );
                }),
            );
        });
    }
    disconnect() {
        this.observer.disconnect();
        this.abortController.abort();
    }
    /**
     * @param {Node} node
     * @param {ShadowRoot[]} [shadowRoots]
     */
    findAllShadowRoots(node, shadowRoots = []) {
        const shadowRoot = /** @type {Element} */ (node).shadowRoot;
        if (shadowRoot) {
            shadowRoots.push(shadowRoot);
            this.findAllShadowRoots(shadowRoot, shadowRoots);
        }
        node.childNodes.forEach((child) => {
            this.findAllShadowRoots(child, shadowRoots);
        });
        return shadowRoots;
    }
    /**
     * @param {Element} target
     */
    observe(target) {
        this.observer.observe(target, this.observerOptions);
        //When iframes already exist at "this.target" initialization
        target
            .querySelectorAll("iframe")
            .forEach((el) =>
                this.observeIframe(
                    /** @type {HTMLIFrameElement} */ (el),
                    this.observer,
                    () => this.callback(),
                ),
            );
        //When shadowDom already exist at "this.target" initialization
        this.findAllShadowRoots(target).forEach((shadowRoot) => {
            this.observer.observe(shadowRoot, this.observerOptions);
        });
    }
    /**
     * @param {HTMLIFrameElement} iframeEl
     * @param {MutationObserver} observer
     * @param {Function} callback
     */
    observeIframe(iframeEl, observer, callback) {
        const { signal } = this.abortController;
        const observeIframeContent = () => {
            const contentDocument = iframeEl.contentDocument;
            if (contentDocument) {
                if (!this.observedContentDocuments.has(contentDocument)) {
                    this.observedContentDocuments.add(contentDocument);
                    contentDocument.addEventListener(
                        "load",
                        (event) => {
                            callback();
                            observer.observe(
                                /** @type {Node} */ (event.target),
                                this.observerOptions,
                            );
                        },
                        { signal },
                    );
                }
                if (!iframeEl.src || contentDocument.readyState === "complete") {
                    callback();
                    observer.observe(contentDocument, this.observerOptions);
                }
            }
        };
        observeIframeContent();
        if (!this.observedIframes.has(iframeEl)) {
            this.observedIframes.add(iframeEl);
            iframeEl.addEventListener("load", observeIframeContent, { signal });
        }
    }
}
