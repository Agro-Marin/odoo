// @ts-check
/** @odoo-module native */

/** @module @web/core/action_hook - CallbackRecorder utility and useSetupAction hook for persisting view state across action switches */

import { onMounted, useComponent, useEffect, useExternalListener } from "@odoo/owl";

/** Symbol key used to store scroll position in local action state. */
export const scrollSymbol = Symbol("scroll");

/** CSS selector for the scrollable content area within a view (with or without search panel). */
const CONTENT_SELECTOR =
    ".o_component_with_search_panel > .o_renderer_with_searchpanel," +
    ".o_component_with_search_panel > .o_renderer";

/**
 * Registry of owner-keyed callbacks used by the action system to collect
 * state (context, orderBy, globalState, localState) from nested components
 * during action switches; each callback is removable via its owner.
 */
export class CallbackRecorder {
    constructor() {
        this.setup();
    }
    setup() {
        /** @type {{ owner: any, callback: Function }[]} */
        this._callbacks = [];
    }
    /**
     * @returns {Function[]}
     */
    get callbacks() {
        return this._callbacks.map(({ callback }) => callback);
    }
    /**
     * @param {any} owner
     * @param {Function} callback
     */
    add(owner, callback) {
        if (!callback) {
            throw new Error("Missing callback");
        }
        this._callbacks.push({ owner, callback });
    }
    /**
     * @param {any} owner
     */
    remove(owner) {
        this._callbacks = this._callbacks.filter((s) => s.owner !== owner);
    }
}

/**
 * @param {CallbackRecorder} callbackRecorder
 * @param {Function} callback
 */
export function useCallbackRecorder(callbackRecorder, callback) {
    const component = useComponent();
    useEffect(
        () => {
            callbackRecorder.add(component, callback);
            return () => callbackRecorder.remove(component);
        },
        () => [],
    );
}

/**
 * OWL hook that wires a component into the action lifecycle: registers
 * callbacks on the matching env CallbackRecorders and handles scroll
 * position save/restore when `rootRef` is provided.
 *
 * @param {Object} [params]
 * @param {Function} [params.beforeVisibilityChange] - called on document visibilitychange
 * @param {Function} [params.beforeUnload] - called on window beforeunload
 * @param {Function} [params.beforeLeave] - called before navigating away from the action
 * @param {Function} [params.getGlobalState] - returns state to persist across action switches
 * @param {Function} [params.getLocalState] - returns state to persist for browser back/forward
 * @param {import("@odoo/owl").Ref} [params.rootRef] - component root ref for scroll tracking
 * @param {Function} [params.getContext] - returns additional context for the action
 * @param {Function} [params.getOrderBy] - returns orderBy for the action
 * @returns {{ setScrollFromState: Function }}
 */
export function useSetupAction(params = {}) {
    const component = useComponent();
    const {
        __beforeLeave__,
        __getGlobalState__,
        __getLocalState__,
        __getContext__,
        __getOrderBy__,
    } = component.env;

    const {
        beforeVisibilityChange,
        beforeUnload,
        beforeLeave,
        getGlobalState,
        getLocalState,
        getContext,
        getOrderBy,
        rootRef,
    } = params;

    if (beforeVisibilityChange) {
        useExternalListener(
            document,
            "visibilitychange",
            /** @type {EventListener} */ (beforeVisibilityChange),
        );
    }

    if (beforeUnload) {
        useExternalListener(
            window,
            "beforeunload",
            /** @type {EventListener} */ (beforeUnload),
        );
    }
    if (__beforeLeave__ && beforeLeave) {
        useCallbackRecorder(__beforeLeave__, beforeLeave);
    }
    // Only `rootRef` feeds LOCAL state (scroll position), never GLOBAL state, so
    // gating the global recorder on `rootRef` registered a callback that always
    // returned `{}` — a no-op. Register it only when `getGlobalState` exists.
    if (__getGlobalState__ && getGlobalState) {
        useCallbackRecorder(__getGlobalState__, () => {
            const state = {};
            Object.assign(state, getGlobalState());
            return state;
        });
    }

    function setScrollFromState() {
        const { state } = component.props;
        const scrolling = state && state[scrollSymbol];
        if (scrolling && rootRef?.el) {
            if (component.env.isSmall) {
                rootRef.el.scrollTop = (scrolling.root && scrolling.root.top) || 0;
                rootRef.el.scrollLeft = (scrolling.root && scrolling.root.left) || 0;
            } else if (scrolling.content) {
                const contentEl =
                    rootRef.el.querySelector(CONTENT_SELECTOR) ||
                    rootRef.el.querySelector(".o_content");
                if (contentEl) {
                    contentEl.scrollTop = scrolling.content.top || 0;
                    contentEl.scrollLeft = scrolling.content.left || 0;
                }
            }
        }
    }
    if (__getLocalState__ && (getLocalState || rootRef)) {
        useCallbackRecorder(__getLocalState__, () => {
            /** @type {Record<PropertyKey, any>} */
            const state = {};
            if (getLocalState) {
                Object.assign(state, getLocalState());
            }
            if (rootRef) {
                if (component.env.isSmall) {
                    state[scrollSymbol] = {
                        root: {
                            left: rootRef.el.scrollLeft,
                            top: rootRef.el.scrollTop,
                        },
                    };
                } else {
                    const contentEl =
                        rootRef.el.querySelector(CONTENT_SELECTOR) ||
                        rootRef.el.querySelector(".o_content");
                    if (contentEl) {
                        state[scrollSymbol] = {
                            content: {
                                left: contentEl.scrollLeft,
                                top: contentEl.scrollTop,
                            },
                        };
                    }
                }
            }
            return state;
        });

        if (rootRef) {
            onMounted(() => setScrollFromState());
        }
    }
    if (__getContext__ && getContext) {
        useCallbackRecorder(__getContext__, getContext);
    }
    if (__getOrderBy__ && getOrderBy) {
        useCallbackRecorder(__getOrderBy__, getOrderBy);
    }

    return {
        setScrollFromState,
    };
}
