// @ts-check
/** @odoo-module native */

import { validate } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { isVisible } from "@web/core/utils/dom/ui";

const macroSchema = {
    name: { type: String, optional: true },
    timeout: { type: Number, optional: true },
    steps: {
        type: Array,
        element: {
            type: Object,
            shape: {
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
 * @template T
 * @param {() => T} predicate
 * @param {{ signal?: AbortSignal }} [options]
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
    /** @type {(() => void) | undefined} */
    let onAbort;
    return new Promise((resolve, reject) => {
        onAbort = () =>
            reject(new DOMException("waitUntil has been aborted", "AbortError"));
        signal?.addEventListener("abort", onAbort, { once: true });
        const runCheck = () => {
            let result;
            try {
                result = predicate();
            } catch (error) {
                reject(error);
                return;
            }
            if (result) {
                resolve(result);
                return;
            }
            handle = browser.requestAnimationFrame(runCheck);
        };
        handle = browser.requestAnimationFrame(runCheck);
    }).finally(() => {
        browser.cancelAnimationFrame(handle);
        if (onAbort) {
            signal?.removeEventListener("abort", onAbort);
        }
    });
}

/**
 * @typedef {{ action?: Function, timeout?: number, trigger?: Function | string }} MacroStep
 */

export class Macro {
    /**
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
        /** @type {Function} */
        this.onComplete = this.onComplete ?? (() => {});
        /** @type {Function} */
        this.onStep = this.onStep ?? (() => {});
        /** @type {(info: { error: Error, step: MacroStep, index: number }) => void} */
        this.onError =
            this.onError ??
            (({ error, step, index }) => {
                console.error(error.message ?? error, step, index);
            });
    }

    async start() {
        await this.advance();
    }

    async advance() {
        while (true) {
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
                /** @type {ReturnType<typeof browser.setTimeout> | undefined} */
                let timerHandle;
                const timerPromise = new Promise((resolve, reject) => {
                    timerHandle = browser.setTimeout(() => {
                        abortController.abort();
                        reject(
                            new MacroError(
                                "Timeout",
                                `TIMEOUT step failed to complete within ${timeoutDelay} ms.`,
                            ),
                        );
                    }, timeoutDelay);
                });
                const stepPromise = executeStep();
                stepPromise.catch(() => {});
                let actionResult;
                try {
                    actionResult = await Promise.race([stepPromise, timerPromise]);
                } finally {
                    browser.clearTimeout(timerHandle);
                }
                if (actionResult) {
                    if (actionResult !== Macro.STOP) {
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
        }
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
        this.abortController = new AbortController();
        /** @type {WeakSet<HTMLIFrameElement>} */
        this.observedIframes = new WeakSet();
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
        /** @type {any[]} */
        const stack = [node];
        while (stack.length) {
            const current = stack.pop();
            const children = current?.children;
            if (!children) {
                continue;
            }
            for (let i = children.length - 1; i >= 0; i--) {
                stack.push(children[i]);
            }
            const shadowRoot = current.shadowRoot;
            if (shadowRoot) {
                shadowRoots.push(shadowRoot);
                stack.push(shadowRoot);
            }
        }
        return shadowRoots;
    }
    /**
     * @param {Element} target
     */
    observe(target) {
        this.observer.observe(target, this.observerOptions);
        target
            .querySelectorAll("iframe")
            .forEach((el) =>
                this.observeIframe(
                    /** @type {HTMLIFrameElement} */ (el),
                    this.observer,
                    () => this.callback(),
                ),
            );
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
            if (
                contentDocument &&
                (!iframeEl.src || contentDocument.readyState === "complete")
            ) {
                callback();
                observer.observe(contentDocument, this.observerOptions);
            }
        };
        observeIframeContent();
        if (!this.observedIframes.has(iframeEl)) {
            this.observedIframes.add(iframeEl);
            iframeEl.addEventListener("load", observeIframeContent, { signal });
        }
    }
}
