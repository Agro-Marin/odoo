/** @odoo-module native */
import {
    onMounted,
    onPatched,
    useComponent,
    useExternalListener,
    useRef,
    useState,
} from "@odoo/owl";
import { makeLogger } from "@web/core/debug/debug_logger";
import { KeepLast } from "@web/core/utils/concurrency";
const log = makeLogger("pos.hooks");

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
            log.logic("useAsyncLockedMethod: call dropped, locked", () => ({
                component: component.constructor.name,
                method: method.name,
            }));
            return;
        }
        const endCall = log.perf(
            `${component.constructor.name}.${method.name || "anonymous"}`,
        );
        try {
            called = true;
            return await method.call(component, ...args);
        } finally {
            called = false;
            endCall();
        }
    };
}

/**
 * @param {(...args: any[]) => Promise<any>} asyncFn
 * @param {{ keepLast?: boolean }} [options]
 */
export function useTrackedAsync(asyncFn, options = {}) {
    /**
     * @type {{
     * status: 'idle' | 'loading' | 'error' | 'success',
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

    let lastCallId = 0;
    const baseMethod = async (...args) => {
        const callId = ++lastCallId;
        state.status = "loading";
        state.result = null;
        state.lastArgs = args;
        const endCall = log.perf(`useTrackedAsync ${asyncFn.name || "anonymous"}`);
        try {
            const result = await asyncFn(...args);
            if (callId !== lastCallId) {
                endCall({ callId, superseded: true });
                return;
            }
            state.status = "success";
            state.result = result;
            endCall({ callId, status: "success" });
        } catch (error) {
            if (callId !== lastCallId) {
                endCall({ callId, superseded: true, error: error?.message });
                return;
            }
            state.status = "error";
            state.result = error;
            endCall({ callId, status: "error", error: error?.message });
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
        log.logic("useIsChildLarger: computeSize", () => ({
            children: container.el.children.length,
            containerWidth,
            isLarger,
            maxItems: state.maxItems,
        }));
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
