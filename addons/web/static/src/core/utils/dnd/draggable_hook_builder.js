// @ts-check
/** @odoo-module native */

import { DragSession } from "./drag_session.js";
import {
    DEFAULT_ACCEPTED_PARAMS,
    DEFAULT_DEFAULT_PARAMS,
    DRAGGED_CLASS,
    getReturnValue,
} from "./draggable_hook_builder_utils.js";
import {
    applyParamsToContext,
    checkParams,
    computeParamValues,
    makeDraggableContext,
    resolveParams,
} from "./draggable_hook_params.js";

export { DRAGGED_CLASS };

/**
 * @typedef {ReturnType<typeof import("./draggable_hook_builder_utils.js")["makeCleanupManager"]>} CleanupManager
 * @typedef {ReturnType<typeof import("./draggable_hook_builder_utils.js")["makeDOMHelpers"]>} DOMHelpers
 * @typedef DraggableBuilderParams
 * @property {string} [name="useAnonymousDraggable"]
 * @property {EdgeScrollingOptions} [edgeScrolling]
 * @property {Record<string, string[]>} [acceptedParams]
 * @property {Record<string, any>} [defaultParams]
 * @property {{
 * @property {(params: DraggableBuildHandlerParams) => any} onComputeParams
 * @property {(params: DraggableBuildHandlerParams) => any} onDragStart
 * @property {(params: DraggableBuildHandlerParams) => any} onDrag
 * @property {(params: DraggableBuildHandlerParams) => any} onDragEnd
 * @property {(params: DraggableBuildHandlerParams) => any} onDrop
 * @property {(params: DraggableBuildHandlerParams) => any} onWillStartDrag
 * @typedef {{
 * @typedef {{
 * @typedef EdgeScrollingOptions
 * @property {boolean} [enabled=true]
 * @property {number} speed
 * @property {number} threshold
 * @property {"horizontal"|"vertical"} [direction]
 * @typedef Position
 * @property {number} x
 * @property {number} y
 * @typedef {DOMHelpers & {
 * @typedef {DOMHelpers & Position & { element: HTMLElement }} DraggableHandlerParams
 */

/**
 * @param {DraggableBuilderParams} hookParams
 * @returns {(params: Record<keyof typeof DEFAULT_ACCEPTED_PARAMS, any>) => { dragging: boolean }}
 */
export function makeNativeDraggableHook(hookParams) {
    hookParams = getReturnValue(hookParams);

    const hookName = hookParams.name || "useAnonymousDraggable";
    const { setupHooks } = hookParams;
    /** @type {Record<string, any[]>} */
    const allAcceptedParams = {
        ...DEFAULT_ACCEPTED_PARAMS,
        ...hookParams.acceptedParams,
    };
    /** @type {Record<string, any>} */
    const defaultParams = {
        ...DEFAULT_DEFAULT_PARAMS,
        ...hookParams.defaultParams,
    };
    const paramKeys = Object.keys(allAcceptedParams);

    /**
     * @param {string} reason
     * @returns {Error}
     */
    const makeError = (reason) => new Error(`Error in hook ${hookName}: ${reason}.`);

    return {
        [hookName](/** @type {Record<string, any>} */ params) {
            const state = setupHooks.wrapState({ dragging: false, willDrag: false });
            checkParams(params, allAcceptedParams, defaultParams, makeError);

            /** @type {DraggableHookContext} */
            const ctx = makeDraggableContext(params.ref, state);
            const session = new DragSession({
                ctx,
                state,
                params,
                hookParams: /** @type {Record<string, any>} */ (hookParams),
            });

            setupHooks.setup(
                (...deps) => {
                    const { computedParams, actualParams } = resolveParams(
                        paramKeys,
                        params,
                        deps,
                        defaultParams,
                    );
                    if (!ctx.ref.el) {
                        return;
                    }
                    applyParamsToContext(ctx, actualParams, computedParams, makeError);
                    session.callBuildHandler("onComputeParams", {
                        params: actualParams,
                    });
                    return session.effectCleanup.cleanup;
                },
                () => computeParamValues(paramKeys, allAcceptedParams, params),
            );

            setupHooks.setup(
                (el) => (el ? session.attachElementListeners(el) : undefined),
                () => [ctx.ref.el],
            );

            session.throttledOnPointerMove = setupHooks.throttle(session.onPointerMove);
            setupHooks.teardown(() => session.dragEnd(null));

            return state;
        },
    }[hookName];
}
