// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { CallbackRecorder } from "@web/core/action_hook";
import {
    actionContextCallbacks,
    actionContextRecorder,
} from "@web/core/action_context_port";

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
        // web_studio opts out by setting all five slots to null; before the
        // port, `null` and `undefined` reached consumers as different shapes.
        expect(
            actionContextRecorder({ __getContext__: null }, "__getContext__").callbacks,
        ).toEqual([]);
    });

    test("tolerates a missing env rather than throwing on the read", () => {
        // The case under test is precisely the undefined the signature
        // forbids: the recorder must tolerate it rather than throw.
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
        // This is the whole point: `_getIrFilterDescription` maps over the
        // result, and used to throw a TypeError when the slot was nulled.
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
        // A null-object that could be written to would silently accept
        // callbacks nobody will ever call -- the failure this port exists to
        // avoid spreading.
        const recorder = actionContextRecorder({}, "__beforeLeave__");
        expect(Object.isFrozen(recorder)).toBe(true);
        expect(actionContextRecorder({}, "__getOrderBy__")).toBe(recorder);
    });
});
