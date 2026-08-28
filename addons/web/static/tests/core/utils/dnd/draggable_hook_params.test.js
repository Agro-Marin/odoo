// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import {
    DEFAULT_ACCEPTED_PARAMS,
    DEFAULT_DEFAULT_PARAMS,
} from "@web/core/utils/dnd/draggable_hook_builder_utils";
import {
    applyParamsToContext,
    computeParamValues,
    makeDraggableContext,
    resolveParams,
    validateParams,
} from "@web/core/utils/dnd/draggable_hook_params";

describe.current.tags("headless");

const PARAM_KEYS = Object.keys(DEFAULT_ACCEPTED_PARAMS);
/** @param {string} reason */
const makeError = (reason) => new Error(`Error in hook useProbe: ${reason}.`);

/** @param {Record<string, any>} [over] */
function ctxWith(over = {}) {
    const state = { dragging: false, willDrag: false };
    return Object.assign(makeDraggableContext({ el: null }, state), over);
}

test("computeParamValues yields one slot per accepted param, in key order", () => {
    const values = computeParamValues(PARAM_KEYS, DEFAULT_ACCEPTED_PARAMS, {});
    expect(values).toHaveLength(PARAM_KEYS.length);
    expect(values.every((v) => v === undefined)).toBe(true, {
        message: "a param the caller did not pass reads as undefined",
    });
});

test("computeParamValues unwraps value getters but not callbacks", () => {
    /** @type {{ el: any }} */
    const ref = { el: null };
    const enable = () => false;
    const preventDrag = () => true;
    const values = computeParamValues(PARAM_KEYS, DEFAULT_ACCEPTED_PARAMS, {
        ref,
        elements: () => ".item",
        enable,
        preventDrag,
    });
    const at = (/** @type {string} */ name) => values[PARAM_KEYS.indexOf(name)];

    expect(at("elements")).toBe(".item", { message: "a value getter is called" });
    expect(at("enable")).toBe(enable);
    expect(at("preventDrag")).toBe(preventDrag);
});

test("validateParams rejects a wrong type and names both sides", () => {
    expect(() =>
        validateParams(
            { ref: {}, elements: 42 },
            DEFAULT_ACCEPTED_PARAMS,
            DEFAULT_DEFAULT_PARAMS,
            makeError,
        ),
    ).toThrow(/invalid type for property "elements".*got number/);
});

test("validateParams rejects a missing mandatory param", () => {
    expect(() =>
        validateParams({}, DEFAULT_ACCEPTED_PARAMS, DEFAULT_DEFAULT_PARAMS, makeError),
    ).toThrow(/missing required property "ref"/);
});

test("validateParams accepts a falsy value for a param that has a default", () => {
    expect(() =>
        validateParams(
            { ref: {}, delay: 0 },
            DEFAULT_ACCEPTED_PARAMS,
            DEFAULT_DEFAULT_PARAMS,
            makeError,
        ),
    ).not.toThrow();
});

test("resolveParams layers what the caller passed over the defaults", () => {
    const deps = computeParamValues(PARAM_KEYS, DEFAULT_ACCEPTED_PARAMS, {
        elements: ".item",
    });
    const { actualParams } = resolveParams(
        PARAM_KEYS,
        { elements: ".item" },
        deps,
        DEFAULT_DEFAULT_PARAMS,
    );
    expect(actualParams.elements).toBe(".item");
    expect(actualParams.tolerance).toBe(DEFAULT_DEFAULT_PARAMS.tolerance);
});

test("resolveParams merges edgeScrolling instead of replacing it", () => {
    const params = { elements: ".item", edgeScrolling: { speed: 99 } };
    const deps = computeParamValues(PARAM_KEYS, DEFAULT_ACCEPTED_PARAMS, params);
    const { actualParams } = resolveParams(
        PARAM_KEYS,
        params,
        deps,
        DEFAULT_DEFAULT_PARAMS,
    );
    expect(actualParams.edgeScrolling.speed).toBe(99);
    expect(actualParams.edgeScrolling.threshold).toBe(
        DEFAULT_DEFAULT_PARAMS.edgeScrolling.threshold,
        { message: "a partial edgeScrolling keeps the default threshold" },
    );
});

test("resolveParams always supplies an `enable` predicate", () => {
    const deps = computeParamValues(PARAM_KEYS, DEFAULT_ACCEPTED_PARAMS, {});
    const { actualParams } = resolveParams(
        PARAM_KEYS,
        {},
        deps,
        DEFAULT_DEFAULT_PARAMS,
    );
    expect(typeof actualParams.enable).toBe("function");
    expect(actualParams.enable()).toBe(true);
});

test("applyParamsToContext joins handle onto elements to form the full selector", () => {
    const ctx = ctxWith();
    applyParamsToContext(
        ctx,
        { ...DEFAULT_DEFAULT_PARAMS, elements: ".item", handle: ".handle" },
        {},
        makeError,
    );
    expect(ctx.elementSelector).toBe(".item");
    expect(ctx.fullSelector).toBe(".item .handle");
});

test("applyParamsToContext leaves fullSelector as elements when there is no handle", () => {
    const ctx = ctxWith();
    applyParamsToContext(
        ctx,
        { ...DEFAULT_DEFAULT_PARAMS, elements: ".item" },
        {},
        makeError,
    );
    expect(ctx.fullSelector).toBe(".item");
});

test("applyParamsToContext throws when the elements selector resolves to nothing", () => {
    expect(() =>
        applyParamsToContext(
            ctxWith(),
            { ...DEFAULT_DEFAULT_PARAMS, elements: "" },
            {},
            makeError,
        ),
    ).toThrow(/no value found by "elements" selector/);
});

test("touchDelay follows an explicit delay, but only when the caller gave one", () => {
    const a = ctxWith();
    applyParamsToContext(
        a,
        { ...DEFAULT_DEFAULT_PARAMS, elements: ".item", delay: 500 },
        { delay: 500 },
        makeError,
    );
    expect(a.touchDelay).toBe(500);

    const b = ctxWith();
    applyParamsToContext(
        b,
        { ...DEFAULT_DEFAULT_PARAMS, elements: ".item" },
        {},
        makeError,
    );
    expect(b.touchDelay).toBe(DEFAULT_DEFAULT_PARAMS.touchDelay);

    const c = ctxWith();
    applyParamsToContext(
        c,
        { ...DEFAULT_DEFAULT_PARAMS, elements: ".item", delay: 500 },
        { delay: 500, touchDelay: 10 },
        makeError,
    );
    expect(c.touchDelay).toBe(10);
});

test("the context reads dragging and willDrag off the live state", () => {
    const state = { dragging: false, willDrag: false };
    const ctx = makeDraggableContext({ el: null }, state);
    expect(ctx.dragging).toBe(false);
    expect(ctx.willDrag).toBe(false);
    state.dragging = true;
    state.willDrag = true;
    expect(ctx.dragging).toBe(true, { message: "a getter, not a copy" });
    expect(ctx.willDrag).toBe(true);
});

test("edgeScrolling starts enabled and detached from the shared default", () => {
    const ctx = makeDraggableContext(
        { el: null },
        { dragging: false, willDrag: false },
    );
    expect(ctx.edgeScrolling.enabled).toBe(true);
    ctx.edgeScrolling.speed = 12345;
    expect(DEFAULT_DEFAULT_PARAMS.edgeScrolling.speed).not.toBe(12345, {
        message: "mutating one context must not poison the module default",
    });
});
