// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import {
    actionContextCallbacks,
    actionContextRecorder,
} from "@web/core/action_context_port";
import { CallbackRecorder } from "@web/core/action_hook";

describe.current.tags("headless");

describe("actionContextRecorder", () => {
    test("returns the installed recorder untouched", () => {
        const recorder = new CallbackRecorder();
        const env = { __getContext__: recorder };
        expect(actionContextRecorder(env, "__getContext__")).toBe(recorder);
    });

    test("substitutes an empty recorder when the slot is absent", () => {
        expect(actionContextRecorder({}, "__getContext__").callbacks).toEqual([]);
    });

    test("treats an explicit null the same as absent", () => {
        expect(
            actionContextRecorder({ __getContext__: null }, "__getContext__").callbacks,
        ).toEqual([]);
    });

    test("tolerates a missing env rather than throwing on the read", () => {
        const recorder = actionContextRecorder(
            /** @type {any} */ (undefined),
            "__getOrderBy__",
        );
        expect(recorder.callbacks).toEqual([]);
    });
});

describe("actionContextCallbacks", () => {
    test("returns the registered callbacks in order", () => {
        const recorder = new CallbackRecorder();
        const one = () => 1;
        const two = () => 2;
        recorder.add({}, one);
        recorder.add({}, two);
        expect(
            actionContextCallbacks({ __getContext__: recorder }, "__getContext__"),
        ).toEqual([one, two]);
    });

    test("returns [] for both off-shapes, so a caller needs no guard", () => {
        for (const env of [
            {},
            { __getContext__: null },
            { __getContext__: undefined },
        ]) {
            expect(actionContextCallbacks(env, "__getContext__")).toEqual([]);
            expect(() =>
                Object.assign(
                    {},
                    ...actionContextCallbacks(env, "__getContext__").map((fn) => fn()),
                ),
            ).not.toThrow();
        }
    });

    test("the substituted recorder is shared and frozen, so a reader cannot record into it", () => {
        const recorder = actionContextRecorder({}, "__beforeLeave__");
        expect(Object.isFrozen(recorder)).toBe(true);
        expect(actionContextRecorder({}, "__getOrderBy__")).toBe(recorder);
    });

    test("recording into the substituted recorder is refused, not silently kept", () => {
        const recorder = actionContextRecorder({}, "__beforeLeave__");
        expect(() => recorder.add({}, () => 1)).toThrow();
        expect(recorder.callbacks).toEqual([]);
        expect(actionContextCallbacks({}, "__getContext__")).toEqual([]);
    });

    test("removing from the substituted recorder is a no-op, not a TypeError", () => {
        const recorder = actionContextRecorder({}, "__getLocalState__");
        expect(() => recorder.remove({})).not.toThrow();
    });
});
