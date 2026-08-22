// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { animationFrame } from "@odoo/hoot-mock";
import { RelationalModel } from "@web/model/relational_model/relational_model";

describe.current.tags("headless");

/**
 * @param {Record<string, any>} [lifecycle]
 * @returns {any}
 */
function makeModel(lifecycle = {}) {
    return new RelationalModel(
        /** @type {any} */ ({ services: {}, bus: { addEventListener() {} } }),
        /** @type {any} */ ({
            config: {
                resModel: "line",
                activeFields: {},
                fields: {},
                isMonoRecord: true,
                context: {},
            },
            hooks: { lifecycle },
        }),
        /** @type {any} */ ({ orm: {} }),
    );
}

describe("subscribeLifecycle only accepts lifecycles that exist", () => {
    test("a known name subscribes", () => {
        const model = makeModel();
        const off = model.subscribeLifecycle("onRecordSaved", () => {});
        expect(off).toBeInstanceOf(Function);
        off();
    });

    test("an unknown name throws instead of registering a listener nothing calls", () => {
        const model = makeModel();
        expect(() => model.subscribeLifecycle("onRecordSavd", () => {})).toThrow(
            /unknown lifecycle "onRecordSavd"/,
            {
                message:
                    "this used to accept any string while only two names were " +
                    "ever dispatched, so a typo reported success and stayed silent",
            },
        );
    });

    test("unsubscribing drops the bucket, so the map does not grow forever", () => {
        const model = makeModel();
        const off = model.subscribeLifecycle("onRootLoaded", () => {});
        expect(model._lifecycleListeners.has("onRootLoaded")).toBe(true);
        off();
        expect(model._lifecycleListeners.has("onRootLoaded")).toBe(false);
    });
});

describe("every lifecycle reaches its subscribers, not just the two that used to", () => {
    const NAMES = [
        "onWillLoadRoot",
        "onRootLoaded",
        "onWillSaveRecord",
        "onRecordSaved",
        "onWillSaveMulti",
        "onSavedMulti",
        "onWillSetInvalidField",
        "onRecordChanged",
        "onWillDisplayOnchangeWarning",
        "onAskMultiSaveConfirmation",
    ];
    for (const name of NAMES) {
        test(`${name} notifies both the hook and a listener`, async () => {
            /** @type {string[]} */
            const seen = [];
            const model = makeModel({ [name]: () => seen.push("hook") });
            model.subscribeLifecycle(name, () => seen.push("listener"));
            await model.notifyLifecycle(name, "arg");
            expect(seen).toEqual(["hook", "listener"], {
                message: "the hook runs first; the listener observes after it",
            });
        });
    }
});

describe("the hook decides, the listener only observes", () => {
    test("notifyLifecycle answers with the HOOK's result, not the listener's", async () => {
        const model = makeModel({ onWillSaveRecord: () => false });
        model.subscribeLifecycle("onWillSaveRecord", () => true);
        expect(await model.notifyLifecycle("onWillSaveRecord")).toBe(false, {
            message: "a subscriber has no standing to overturn a veto",
        });
    });

    test("notifyLifecycle is a promise even with nothing subscribed", () => {
        const model = makeModel({ onWillSaveRecord: () => false });
        expect(model.notifyLifecycle("onWillSaveRecord")).toBeInstanceOf(Promise, {
            message:
                "returning the raw result when idle and a promise when subscribed " +
                "would make every `=== false` veto depend on who else subscribed",
        });
    });

    test("notifyLifecycleSync is never a promise, and runs the hook now", () => {
        /** @type {string[]} */
        const seen = [];
        const model = makeModel({ onWillSetInvalidField: () => seen.push("hook") });
        const result = model.notifyLifecycleSync("onWillSetInvalidField");
        expect(seen).toEqual(["hook"], { message: "synchronously, before returning" });
        expect(result).not.toBeInstanceOf(Promise);
    });

    test("a hook that throws synchronously still throws at the call site", () => {
        const model = makeModel({
            onWillLoadRoot: () => {
                throw new Error("hook-boom");
            },
        });
        expect(() => model.notifyLifecycleSync("onWillLoadRoot")).toThrow(/hook-boom/);
    });
});

describe("hasOnRecordChangedHook is live, not a constructor-time snapshot", () => {
    test("false with no hook and no listener", () => {
        expect(makeModel().hasOnRecordChangedHook).toBe(false);
    });

    test("true for a hook passed at construction", () => {
        expect(makeModel({ onRecordChanged: () => {} }).hasOnRecordChangedHook).toBe(
            true,
        );
    });

    test("true for a hook installed AFTER construction", () => {
        const model = makeModel();
        model.hooks.lifecycle.onRecordChanged = () => {};
        expect(model.hasOnRecordChangedHook).toBe(true, {
            message:
                "this was computed once in setup(), so a hook installed the way " +
                "web_studio installs onRecordSaved would never have fired",
        });
    });

    test("true for a subscriber, and false again once it unsubscribes", () => {
        const model = makeModel();
        const off = model.subscribeLifecycle("onRecordChanged", () => {});
        expect(model.hasOnRecordChangedHook).toBe(true);
        off();
        expect(model.hasOnRecordChangedHook).toBe(false);
    });
});

describe("a listener that rejects is reported, not dropped", () => {
    test("notifyLifecycleSync routes the rejection to the error service", async () => {
        expect.errors(1);
        const model = makeModel();
        model.subscribeLifecycle("onWillLoadRoot", async () => {
            throw new Error("listener-boom");
        });

        model.notifyLifecycleSync("onWillLoadRoot", {});
        await animationFrame();

        expect.verifyErrors(["listener-boom"]);
    });
});
