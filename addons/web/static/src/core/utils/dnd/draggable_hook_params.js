// @ts-check
/** @odoo-module native */

import { omit } from "@web/core/utils/collections/objects";

import {
    DEFAULT_DEFAULT_PARAMS,
    getReturnValue,
    MANDATORY_PARAMS,
    toFunction,
} from "./draggable_hook_builder_utils.js";

/**
 * @import { DraggableHookContext } from "./draggable_hook_builder.js"
 */

/**
 * @param {string[]} paramKeys
 * @param {Record<string, any[]>} allAcceptedParams
 * @param {Record<string, any>} params
 * @returns {any[]}
 */
export function computeParamValues(paramKeys, allAcceptedParams, params) {
    return paramKeys.map((prop) => {
        if (!(prop in params)) {
            return undefined;
        }
        if (
            prop === "enable" ||
            (allAcceptedParams[prop].length === 1 &&
                allAcceptedParams[prop][0] === Function)
        ) {
            return params[prop];
        }
        return getReturnValue(params[prop]);
    });
}

/**
 * @param {Record<string, any>} params
 * @param {Record<string, any[]>} allAcceptedParams
 * @param {Record<string, any>} defaultParams
 * @param {(reason: string) => Error} makeError
 * @returns {void}
 */
export function validateParams(params, allAcceptedParams, defaultParams, makeError) {
    for (const prop of Object.keys(allAcceptedParams)) {
        const type = typeof params[prop];
        const acceptedTypes = allAcceptedParams[prop].map((t) => t.name.toLowerCase());
        if (params[prop]) {
            if (!acceptedTypes.includes(type)) {
                throw makeError(
                    `invalid type for property "${prop}" in parameters: expected { ${acceptedTypes.join(
                        ", ",
                    )} } and got ${type}`,
                );
            }
        } else if (MANDATORY_PARAMS.includes(prop) && !defaultParams[prop]) {
            throw makeError(`missing required property "${prop}" in parameters`);
        }
    }
}

/**
 * @param {string[]} paramKeys
 * @param {Record<string, any>} params
 * @param {any[]} deps
 * @param {Record<string, any>} defaultParams
 * @returns {{ computedParams: Record<string, any>, actualParams: Record<string, any> }}
 */
export function resolveParams(paramKeys, params, deps, defaultParams) {
    /** @type {Record<string, any>} */
    const computedParams = { enable: () => true };
    paramKeys.forEach((prop, index) => {
        if (prop in params) {
            computedParams[prop] =
                prop === "enable" ? toFunction(deps[index]) : deps[index];
        }
    });
    /** @type {Record<string, any>} */
    const actualParams = {
        ...defaultParams,
        ...omit(computedParams, "edgeScrolling"),
    };
    if (computedParams.edgeScrolling) {
        actualParams.edgeScrolling = {
            ...actualParams.edgeScrolling,
            ...computedParams.edgeScrolling,
        };
    }
    return { computedParams, actualParams };
}

/**
 * @param {DraggableHookContext} ctx
 * @param {Record<string, any>} actualParams
 * @param {Record<string, any>} computedParams
 * @param {(reason: string) => Error} makeError
 * @returns {void}
 */
export function applyParamsToContext(ctx, actualParams, computedParams, makeError) {
    ctx.enable = actualParams.enable;
    if (actualParams.preventDrag) {
        ctx.preventDrag = actualParams.preventDrag;
    }
    ctx.elementSelector = actualParams.elements;
    if (!ctx.elementSelector) {
        throw makeError(
            `no value found by "elements" selector: ${ctx.elementSelector}`,
        );
    }
    const allSelectors = [ctx.elementSelector];
    ctx.cursor = actualParams.cursor || null;
    if (actualParams.handle) {
        allSelectors.push(actualParams.handle);
    }
    if (actualParams.ignore) {
        ctx.ignoreSelector = actualParams.ignore;
    }
    ctx.fullSelector = allSelectors.join(" ");

    Object.assign(ctx.edgeScrolling, actualParams.edgeScrolling);

    ctx.delay = actualParams.delay;
    ctx.touchDelay =
        computedParams.touchDelay ?? computedParams.delay ?? actualParams.touchDelay;
    ctx.tolerance = actualParams.tolerance;
}

/**
 * @param {{ el: HTMLElement | null }} ref
 * @param {{ dragging: boolean, willDrag: boolean }} state
 * @returns {DraggableHookContext}
 */
export function makeDraggableContext(ref, state) {
    return /** @type {any} */ ({
        enable: () => false,
        preventDrag: () => false,
        ref,
        ignoreSelector: null,
        fullSelector: null,
        followCursor: true,
        cursor: null,
        pointer: { x: 0, y: 0 },
        edgeScrolling: { ...DEFAULT_DEFAULT_PARAMS.edgeScrolling, enabled: true },
        get dragging() {
            return state.dragging;
        },
        get willDrag() {
            return state.willDrag;
        },
        current: {},
    });
}
