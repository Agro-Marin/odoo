// @ts-check

import { registerCleanup } from "@web/../tests/helpers/cleanup";
import {
    click as webClick,
    getFixture,
    makeDeferred,
    triggerEvents as webTriggerEvents,
} from "@web/../tests/helpers/utils";
import { isVisible } from "@web/core/utils/dom/ui";

/**
 * @param {Object[]} files
 * @returns {Object}
 */
function createFakeDataTransfer(files) {
    return {
        dropEffect: "all",
        effectAllowed: "all",
        files,
        items: [],
        types: ["Files"],
    };
}

/**
 * @param {string} selector
 * @param {ContainsOptions} [options]
 * @param {boolean} [options.shiftKey]
 */
export async function click(selector, options = {}) {
    const { shiftKey } = options;
    delete options.shiftKey;
    await contains(selector, { click: { shiftKey }, ...options });
}

/**
 * @param {string} selector
 * @param {Object[]} files
 * @param {ContainsOptions} [options]
 */
export async function dragenterFiles(selector, files, options) {
    await contains(selector, { dragenterFiles: files, ...options });
}

/**
 * @param {string} selector
 * @param {Object[]} files
 * @param {ContainsOptions} [options]
 */
export async function dragoverFiles(selector, files, options) {
    await contains(selector, { dragoverFiles: files, ...options });
}

/**
 * @param {string} selector
 * @param {Object[]} files
 * @param {ContainsOptions} [options]
 */
export async function dropFiles(selector, files, options) {
    await contains(selector, { dropFiles: files, ...options });
}

/**
 * @param {string} selector
 * @param {Object[]} files
 * @param {ContainsOptions} [options]
 */
export async function inputFiles(selector, files, options) {
    await contains(selector, { inputFiles: files, ...options });
}

/**
 * @param {string} selector
 * @param {Object[]} files
 * @param {ContainsOptions} [options]
 */
export async function pasteFiles(selector, files, options) {
    await contains(selector, { pasteFiles: files, ...options });
}

/**
 * @param {string} selector
 * @param {ContainsOptions} [options]
 */
export async function focus(selector, options) {
    await contains(selector, { setFocus: true, ...options });
}

/**
 * @param {string} selector
 * @param {string} content
 * @param {ContainsOptions} [options]
 * @param {boolean} [options.replace=false]
 */
export async function insertText(selector, content, options = {}) {
    const { replace = false } = options;
    delete options.replace;
    await contains(selector, { ...options, insertText: { content, replace } });
}

/**
 * @param {string} selector
 * @param {number|"bottom"} scrollTop
 * @param {ContainsOptions} [options]
 */
export async function scroll(selector, scrollTop, options) {
    await contains(selector, { setScroll: scrollTop, ...options });
}

/**
 * @param {string} selector
 * @param {(import("@web/../tests/helpers/utils").EventType|[import("@web/../tests/helpers/utils").EventType, EventInit])[]} events
 * @param {ContainsOptions} [options]
 */
export async function triggerEvents(selector, events, options) {
    await contains(selector, { triggerEvents: events, ...options });
}

function log(ok, message) {
    if (ok) {
        console.log(message);
    } else {
        console.error(message);
    }
}

let hasUsedContainsPositively = false;
/**
 * @typedef {[string, ContainsOptions]} ContainsTuple
 * @typedef {Object} ContainsOptions
 * @property {ContainsTuple} [after]
 * @property {ContainsTuple} [before]
 * @property {Object} [click]
 * @property {ContainsTuple|ContainsTuple[]} [contains]
 * @property {number} [count=1]
 * @property {Object[]} [dragenterFiles]
 * @property {Object[]} [dragoverFiles]
 * @property {Object[]} [dropFiles]
 * @property {Object[]} [inputFiles]
 * @property {{content:string, replace:boolean}} [insertText]
 * @property {ContainsTuple} [parent]
 * @property {Object[]} [pasteFiles]
 * @property {number|"bottom"} [scroll]
 * @property {boolean} [setFocus]
 * @property {boolean} [shadowRoot]
 * @property {number|"bottom"} [setScroll]
 * @property {Element} [target=getFixture()]
 * @property {(import("@web/../tests/helpers/utils").EventType | [import("@web/../tests/helpers/utils").EventType, EventInit])[]} [triggerEvents]
 * @property {string} [text]
 * @property {string} [textContent]
 * @property {string} [value]
 * @property {boolean} [visible]
 */
class Contains {
    /**
     * @param {string} selector
     * @param {ContainsOptions} [options={}]
     */
    constructor(selector, options = {}) {
        this.selector = selector;
        this.options = options;
        this.options.count ??= 1;
        this.options.targetParam = this.options.target;
        this.options.target ??= getFixture();
        let selectorMessage = `${this.options.count} of "${this.selector}"`;
        if (this.options.visible !== undefined) {
            selectorMessage = `${selectorMessage} ${
                this.options.visible ? "visible" : "invisible"
            }`;
        }
        if (this.options.targetParam) {
            selectorMessage = `${selectorMessage} inside a specific target`;
        }
        if (this.options.parent) {
            selectorMessage = `${selectorMessage} inside a specific parent`;
        }
        if (this.options.contains) {
            selectorMessage = `${selectorMessage} with a specified sub-contains`;
        }
        if (this.options.text !== undefined) {
            selectorMessage = `${selectorMessage} with text "${this.options.text}"`;
        }
        if (this.options.textContent !== undefined) {
            selectorMessage = `${selectorMessage} with textContent "${this.options.textContent}"`;
        }
        if (this.options.value !== undefined) {
            selectorMessage = `${selectorMessage} with value "${this.options.value}"`;
        }
        if (this.options.scroll !== undefined) {
            selectorMessage = `${selectorMessage} with scroll "${this.options.scroll}"`;
        }
        if (this.options.after !== undefined) {
            selectorMessage = `${selectorMessage} after a specified element`;
        }
        if (this.options.before !== undefined) {
            selectorMessage = `${selectorMessage} before a specified element`;
        }
        this.selectorMessage = selectorMessage;
        if (this.options.contains && !Array.isArray(this.options.contains[0])) {
            this.options.contains = [this.options.contains];
        }
        if (this.options.count) {
            hasUsedContainsPositively = true;
        } else if (!hasUsedContainsPositively) {
            throw new Error(
                `Starting a test with "contains" of count 0 for selector "${this.selector}" is useless because it might immediately resolve. Start the test by checking that an expected element actually exists.`,
            );
        }
        /** @type {string} */
        this.successMessage = undefined;
        /** @type {function} */
        this.executeError = undefined;
    }

    /**
     * @returns {Promise}
     */
    run() {
        this.done = false;
        this.def = makeDeferred();
        this.scrollListeners = new Set();
        this.onScroll = () => this.runOnce("after scroll");
        if (!this.runOnce("immediately")) {
            this.timer = setTimeout(
                () => this.runOnce("Timeout of 5 seconds", { crashOnFail: true }),
                5000,
            );
            this.observer = new MutationObserver((mutations) => {
                try {
                    this.runOnce("after mutations");
                } catch (e) {
                    this.def.reject(e);
                }
            });
            this.observer.observe(this.options.target, {
                attributes: true,
                childList: true,
                subtree: true,
            });
            registerCleanup(() => {
                if (!this.done) {
                    this.runOnce("Test ended", { crashOnFail: true });
                }
            });
        }
        return this.def;
    }

    /**
     * @param {string} whenMessage
     * @param {Object} [options={}]
     * @param {boolean} [options.crashOnFail=false]
     * @param {boolean} [options.executeOnSuccess=true]
     * @returns {HTMLElement[]|undefined}
     */
    runOnce(whenMessage, { crashOnFail = false, executeOnSuccess = true } = {}) {
        const res = this.select();
        if (res?.length === this.options.count || crashOnFail) {
            this.observer?.disconnect();
            clearTimeout(this.timer);
            for (const el of this.scrollListeners ?? []) {
                el.removeEventListener("scroll", this.onScroll);
            }
            this.done = true;
        }
        if (res?.length === this.options.count) {
            this.successMessage = `Found ${this.selectorMessage} (${whenMessage})`;
            if (executeOnSuccess) {
                this.executeAction(res[0]);
            }
            return res;
        } else {
            this.executeError = () => {
                let message = `Failed to find ${this.selectorMessage} (${whenMessage}).`;
                message = res
                    ? `${message} Found ${res.length} instead.`
                    : `${message} Parent not found.`;
                if (this.parentContains) {
                    if (this.parentContains.successMessage) {
                        log(true, this.parentContains.successMessage);
                    } else {
                        this.parentContains.executeError();
                    }
                }
                log(false, message);
                this.def?.reject(new Error(message));
                for (const childContains of this.childrenContains || []) {
                    if (childContains.successMessage) {
                        log(true, childContains.successMessage);
                    } else {
                        childContains.executeError();
                    }
                }
            };
            if (crashOnFail) {
                this.executeError();
            }
        }
    }

    /**
     * @param {HTMLElement} el
     */
    executeAction(el) {
        let message = this.successMessage;
        if (this.options.click) {
            message = `${message} and clicked it`;
            webClick(el, undefined, {
                mouseEventInit: this.options.click,
                skipDisabledCheck: true,
                skipVisibilityCheck: true,
            });
        }
        if (this.options.dragenterFiles) {
            message = `${message} and dragentered ${this.options.dragenterFiles.length} file(s)`;
            const ev = new Event("dragenter", { bubbles: true });
            Object.defineProperty(ev, "dataTransfer", {
                value: createFakeDataTransfer(this.options.dragenterFiles),
            });
            el.dispatchEvent(ev);
        }
        if (this.options.dragoverFiles) {
            message = `${message} and dragovered ${this.options.dragoverFiles.length} file(s)`;
            const ev = new Event("dragover", { bubbles: true });
            Object.defineProperty(ev, "dataTransfer", {
                value: createFakeDataTransfer(this.options.dragoverFiles),
            });
            el.dispatchEvent(ev);
        }
        if (this.options.dropFiles) {
            message = `${message} and dropped ${this.options.dropFiles.length} file(s)`;
            const ev = new Event("drop", { bubbles: true });
            Object.defineProperty(ev, "dataTransfer", {
                value: createFakeDataTransfer(this.options.dropFiles),
            });
            el.dispatchEvent(ev);
        }
        if (this.options.inputFiles) {
            message = `${message} and inputted ${this.options.inputFiles.length} file(s)`;
            const dataTransfer = new window.DataTransfer();
            for (const file of this.options.inputFiles) {
                dataTransfer.items.add(file);
            }
            el.files = dataTransfer.files;
            const versionRaw = navigator.userAgent.match(/Chrom(e|ium)\/([0-9]+)\./);
            const chromeVersion = versionRaw ? parseInt(versionRaw[2], 10) : false;
            if (!chromeVersion || chromeVersion >= 73) {
                el.dispatchEvent(new Event("change"));
            }
        }
        if (this.options.insertText !== undefined) {
            message = `${message} and inserted text "${this.options.insertText.content}" (replace: ${this.options.insertText.replace})`;
            el.focus();
            if (this.options.insertText.replace) {
                el.value = "";
                el.dispatchEvent(
                    new window.KeyboardEvent("keydown", { key: "Backspace" }),
                );
                el.dispatchEvent(
                    new window.KeyboardEvent("keyup", { key: "Backspace" }),
                );
                el.dispatchEvent(new window.InputEvent("input"));
            }
            for (const char of this.options.insertText.content) {
                el.value += char;
                el.dispatchEvent(new window.KeyboardEvent("keydown", { key: char }));
                el.dispatchEvent(new window.KeyboardEvent("keyup", { key: char }));
                el.dispatchEvent(new window.InputEvent("input"));
            }
            el.dispatchEvent(new window.InputEvent("change"));
        }
        if (this.options.pasteFiles) {
            message = `${message} and pasted ${this.options.pasteFiles.length} file(s)`;
            const ev = new Event("paste", { bubbles: true });
            Object.defineProperty(ev, "clipboardData", {
                value: createFakeDataTransfer(this.options.pasteFiles),
            });
            el.dispatchEvent(ev);
        }
        if (this.options.setFocus) {
            message = `${message} and focused it`;
            el.focus();
        }
        if (this.options.setScroll !== undefined) {
            message = `${message} and set scroll to "${this.options.setScroll}"`;
            el.scrollTop =
                this.options.setScroll === "bottom"
                    ? el.scrollHeight
                    : this.options.setScroll;
        }
        if (this.options.triggerEvents) {
            message = `${message} and triggered "${this.options.triggerEvents.join(", ")}" events`;
            webTriggerEvents(el, null, this.options.triggerEvents, {
                skipVisibilityCheck: true,
            });
        }
        if (this.parentContains) {
            log(true, this.parentContains.successMessage);
        }
        log(true, message);
        for (const childContains of this.childrenContains) {
            log(true, childContains.successMessage);
        }
        this.def?.resolve();
    }

    /**
     * @returns {HTMLElement[]|undefined}
     */
    select() {
        const target = this.selectParent();
        if (!target) {
            return;
        }
        const baseRes = [...target.querySelectorAll(this.selector)]
            .map((el) => (this.options.shadowRoot ? el.shadowRoot : el))
            .filter((el) => el);
        /** @type {Contains[]} */
        this.childrenContains = [];
        const res = baseRes.filter((el, currentIndex) => {
            let condition =
                (this.options.textContent === undefined ||
                    el.textContent.trim() === this.options.textContent) &&
                (this.options.value === undefined || el.value === this.options.value) &&
                (this.options.scroll === undefined ||
                    (this.options.scroll === "bottom"
                        ? Math.abs(el.scrollHeight - el.clientHeight - el.scrollTop) <=
                          1
                        : Math.abs(el.scrollTop - this.options.scroll) <= 1));
            if (condition && this.options.text !== undefined) {
                if (
                    el.textContent.trim() !== this.options.text &&
                    [...el.querySelectorAll("*")].every(
                        (el) => el.textContent.trim() !== this.options.text,
                    )
                ) {
                    condition = false;
                }
            }
            if (condition && this.options.contains) {
                for (const param of this.options.contains) {
                    const childContains = new Contains(param[0], {
                        ...param[1],
                        target: el,
                    });
                    if (
                        !childContains.runOnce(`as child of el ${currentIndex + 1})`, {
                            executeOnSuccess: false,
                        })
                    ) {
                        condition = false;
                    }
                    this.childrenContains.push(childContains);
                }
            }
            if (condition && this.options.visible !== undefined) {
                if (isVisible(el) !== this.options.visible) {
                    condition = false;
                }
            }
            if (condition && this.options.after) {
                const afterContains = new Contains(this.options.after[0], {
                    ...this.options.after[1],
                    target,
                });
                const afterEl = afterContains.runOnce(`as "after"`, {
                    executeOnSuccess: false,
                })?.[0];
                if (
                    !afterEl ||
                    !(
                        el.compareDocumentPosition(afterEl) &
                        Node.DOCUMENT_POSITION_PRECEDING
                    )
                ) {
                    condition = false;
                }
                this.childrenContains.push(afterContains);
            }
            if (condition && this.options.before) {
                const beforeContains = new Contains(this.options.before[0], {
                    ...this.options.before[1],
                    target,
                });
                const beforeEl = beforeContains.runOnce(`as "before"`, {
                    executeOnSuccess: false,
                })?.[0];
                if (
                    !beforeEl ||
                    !(
                        el.compareDocumentPosition(beforeEl) &
                        Node.DOCUMENT_POSITION_FOLLOWING
                    )
                ) {
                    condition = false;
                }
                this.childrenContains.push(beforeContains);
            }
            return condition;
        });
        if (
            this.options.scroll !== undefined &&
            this.scrollListeners &&
            baseRes.length === this.options.count &&
            res.length !== this.options.count
        ) {
            for (const el of baseRes) {
                if (!this.scrollListeners.has(el)) {
                    this.scrollListeners.add(el);
                    el.addEventListener("scroll", this.onScroll);
                }
            }
        }
        return res;
    }

    /**
     * @returns {Element|undefined}
     */
    selectParent() {
        if (this.options.parent) {
            this.parentContains = new Contains(this.options.parent[0], {
                ...this.options.parent[1],
                target: this.options.target,
            });
            return this.parentContains.runOnce(`as parent`, {
                executeOnSuccess: false,
            })?.[0];
        }
        return this.options.target;
    }
}

/**
 * @param {string} selector
 * @param {ContainsOptions} [options]
 * @returns {Promise}
 */
export async function contains(selector, options) {
    await new Contains(selector, options).run();
}
