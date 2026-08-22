// @ts-check
/** @odoo-module native */

import { onMounted, useComponent, useEffect, useExternalListener } from "@odoo/owl";

export const scrollSymbol = Symbol("scroll");

const CONTENT_SELECTOR =
    ".o_component_with_search_panel > .o_renderer_with_searchpanel," +
    ".o_component_with_search_panel > .o_renderer";

export class CallbackRecorder {
    /**
     * @type {{ owner: any, callback: Function }[]}
     */
    _callbacks = [];
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
 * @param {Object} [params]
 * @param {Function} [params.beforeVisibilityChange]
 * @param {Function} [params.beforeUnload]
 * @param {Function} [params.beforeLeave]
 * @param {Function} [params.getGlobalState]
 * @param {Function} [params.getLocalState]
 * @param {import("@odoo/owl").Ref} [params.rootRef]
 * @param {Function} [params.getContext]
 * @param {Function} [params.getOrderBy]
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
            const rootEl = rootRef?.el;
            if (rootEl) {
                if (component.env.isSmall) {
                    state[scrollSymbol] = {
                        root: {
                            left: rootEl.scrollLeft,
                            top: rootEl.scrollTop,
                        },
                    };
                } else {
                    const contentEl =
                        rootEl.querySelector(CONTENT_SELECTOR) ||
                        rootEl.querySelector(".o_content");
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
