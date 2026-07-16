/** @odoo-module native */
import {
    onMounted,
    onPatched,
    useComponent,
    useExternalListener,
    useRef,
    useState,
} from "@odoo/owl";
import { KeepLast } from "@web/core/utils/concurrency";
// NB: useErrorHandlers/_handlePushOrderError was removed: nothing invoked the
// handler since the validation flow moved to OrderPaymentValidation +
// error_handlers.js (and its "Odoo Server Errors" branch dereferenced a
// traceback string, so it would have thrown if it ever ran).

/**
 * Assumes t-ref="root" in the root element of the component that uses this hook.
 */
export function useAutoFocusToLast() {
    const root = useRef("root");
    let target = null;
    function autofocus() {
        const prevTarget = target;
        const allInputs = root.el.querySelectorAll("input");
        target = allInputs[allInputs.length - 1];
        if (target && target !== prevTarget) {
            target.focus();
            target.selectionStart = target.selectionEnd = target.value.length;
        }
    }
    onMounted(autofocus);
    onPatched(autofocus);
}

export function useAsyncLockedMethod(method) {
    const component = useComponent();
    let called = false;
    return async (...args) => {
        if (called) {
            return;
        }
        try {
            called = true;
            return await method.call(component, ...args);
        } finally {
            called = false;
        }
    };
}

/**
 * Wrapper for an async function that exposes the status of the function call.
 *
 * Sample use case:
 * ```js
 * {
 *   // inside in a component
 *   this.doPrint = useTrackedAsync(() => this.printReceipt())
 *   this.doPrint.status === 'idle'
 *   this.doPrint.call() // triggers the given async function
 *   this.doPrint.status === 'loading'
 *   ['success', 'error].includes(this.doPrint.status) && this.doPrint.result
 * }
 * ```
 * @param {(...args: any[]) => Promise<any>} asyncFn
 * @param {{ keepLast?: boolean }} [options] - Options for managing concurrency.
 */
export function useTrackedAsync(asyncFn, options = {}) {
    /**
     * @type {{
     *  status: 'idle' | 'loading' | 'error' | 'success',
     * result: any,
     * lastArgs: any[]
     * }}
     */
    const state = useState({
        status: "idle",
        result: null,
        lastArgs: null,
    });

    const { keepLast = false } = options;

    // KeepLast only guards the promise returned to the caller — baseMethod
    // mutates the reactive state when it settles regardless, so a slow stale
    // call would overwrite the newer call's result. The call token makes the
    // state writes themselves last-caller-only.
    let lastCallId = 0;
    const baseMethod = async (...args) => {
        const callId = ++lastCallId;
        state.status = "loading";
        state.result = null;
        state.lastArgs = args;
        try {
            const result = await asyncFn(...args);
            if (callId !== lastCallId) {
                return;
            }
            state.status = "success";
            state.result = result;
        } catch (error) {
            if (callId !== lastCallId) {
                return;
            }
            state.status = "error";
            state.result = error;
        }
    };

    let call;
    if (keepLast) {
        const keepLastInstance = new KeepLast();
        call = (...args) => keepLastInstance.add(baseMethod(...args));
    } else {
        call = useAsyncLockedMethod(baseMethod);
    }

    return {
        get status() {
            return state.status;
        },
        get result() {
            return state.result;
        },
        get lastArgs() {
            return state.lastArgs;
        },
        call,
    };
}

export function useIsChildLarger(container) {
    const state = useState({
        isLarger: false,
        maxItems: 0,
    });

    const computeSize = () => {
        if (!container.el || !container.el.children.length) {
            return;
        }

        let acc = 0;
        let nbrItems = 0;
        let isLarger = false;
        const oldLargerState = state.isLarger;
        const containerWidth = container.el.clientWidth - 10;

        for (const child of container.el.children) {
            acc += child.clientWidth;
            if (acc < containerWidth) {
                nbrItems++;
            } else {
                isLarger = true;
                break;
            }
        }

        state.isLarger = isLarger;
        state.maxItems = nbrItems;
        if (!oldLargerState && state.isLarger) {
            state.maxItems--;
        }
    };

    useExternalListener(window, "resize", () => {
        computeSize();
    });

    return {
        get isLarger() {
            return state.isLarger;
        },
        get maxItems() {
            return state.maxItems;
        },
        reload: () => {
            computeSize();
        },
    };
}
