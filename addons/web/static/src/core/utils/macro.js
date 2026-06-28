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
                action: { type: [Function, String], optional: true },
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
 */
async function waitForTrigger(trigger) {
    if (!trigger) {
        return;
    }
    try {
        await delay(50);
        return await waitUntil(() => {
            if (typeof trigger === "function") {
                return trigger();
            } else if (typeof trigger === "string") {
                const triggerEl = document.querySelector(trigger);
                return isVisible(triggerEl) && triggerEl;
            }
        });
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
 * @returns {Promise<T>}
 */
export async function waitUntil(predicate) {
    const result = predicate();
    if (result) {
        return Promise.resolve(result);
    }
    /** @type {number} */
    let handle;
    return new Promise((resolve) => {
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
 * @typedef {{ action?: Function | string, timeout?: number, trigger?: Function | string }} MacroStep
 */

export class Macro {
    currentIndex = 0;
    isComplete = false;
    /** @type {string | undefined} */
    name = undefined;
    /** @type {number | undefined} */
    timeout = undefined;
    /** @type {MacroStep[]} */
    steps = [];
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
            const executeStep = async () => {
                const trigger = await waitForTrigger(step.trigger);
                const result = await performAction(trigger, step.action);
                await this.onStep({ step, trigger, index: this.currentIndex });
                return result;
            };
            const launchTimer = async () => {
                await delay(timeoutDelay);
                throw new MacroError(
                    "Timeout",
                    `TIMEOUT step failed to complete within ${timeoutDelay} ms.`,
                );
            };
            // If falsy action result, it means the action worked properly.
            // So we can proceed to the next step.
            const actionResult = await Promise.race([executeStep(), launchTimer()]);
            if (actionResult) {
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
        const observeIframeContent = () => {
            if (iframeEl.contentDocument) {
                iframeEl.contentDocument.addEventListener("load", (event) => {
                    callback();
                    observer.observe(
                        /** @type {Node} */ (event.target),
                        this.observerOptions,
                    );
                });
                if (
                    !iframeEl.src ||
                    iframeEl.contentDocument.readyState === "complete"
                ) {
                    callback();
                    observer.observe(iframeEl.contentDocument, this.observerOptions);
                }
            }
        };
        observeIframeContent();
        iframeEl.addEventListener("load", observeIframeContent);
    }
}
