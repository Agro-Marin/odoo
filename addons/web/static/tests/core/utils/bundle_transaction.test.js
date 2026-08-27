// @ts-check

import { afterEach, describe, expect, test } from "@odoo/hoot";
import {
    deferUntilBundlesSettled,
    isBundleEvaluating,
    resetBundleTransactions,
    runInBundleTransaction,
} from "@web/core/utils/bundle_transaction";

describe.current.tags("headless");

afterEach(() => resetBundleTransactions());

test("nothing in flight: the caller runs its own reaction", () => {
    expect(isBundleEvaluating()).toBe(false);
    expect(deferUntilBundlesSettled(() => {})).toBe(false);
});

test("a reaction raised during evaluation is held until it finishes", async () => {
    const calls = [];
    const evaluation = runInBundleTransaction(async () => {
        expect(deferUntilBundlesSettled(() => calls.push("reaction"))).toBe(true);
        expect(calls).toEqual([], {
            message: "must not run while the bundle is half applied",
        });
        await Promise.resolve();
        calls.push("second module evaluated");
    });
    await evaluation;
    expect(calls).toEqual(["second module evaluated", "reaction"]);
});

test("many reactions from one bundle collapse into a single run", async () => {
    let runs = 0;
    const react = () => runs++;
    await runInBundleTransaction(async () => {
        for (let i = 0; i < 5; i++) {
            deferUntilBundlesSettled(react);
        }
    });
    expect(runs).toBe(1);
});

test("nesting settles only when the outermost evaluation finishes", async () => {
    const calls = [];
    await runInBundleTransaction(async () => {
        deferUntilBundlesSettled(() => calls.push("outer reaction"));
        await runInBundleTransaction(async () => {
            deferUntilBundlesSettled(() => calls.push("inner reaction"));
        });
        expect(calls).toEqual([], { message: "the inner end must not settle" });
        calls.push("outer still evaluating");
    });
    expect(calls).toEqual([
        "outer still evaluating",
        "outer reaction",
        "inner reaction",
    ]);
});

test("a bundle that throws still settles its reactions", async () => {
    const calls = [];
    await expect(
        runInBundleTransaction(async () => {
            deferUntilBundlesSettled(() => calls.push("reaction"));
            throw new Error("module evaluation failed");
        }),
    ).rejects.toThrow("module evaluation failed");
    expect(calls).toEqual(["reaction"], {
        message: "a failed bundle must not strand held reactions forever",
    });
    expect(isBundleEvaluating()).toBe(false);
});

test("a reaction that throws does not stop the others", async () => {
    const calls = [];
    await runInBundleTransaction(async () => {
        deferUntilBundlesSettled(() => {
            throw new Error("first reaction failed");
        });
        deferUntilBundlesSettled(() => calls.push("second"));
    });
    expect(calls).toEqual(["second"]);
});

test("the value of the evaluation is passed through", async () => {
    expect(await runInBundleTransaction(async () => 42)).toBe(42);
});

test("an async reaction is awaited, so the bundle resolves applied", async () => {
    const calls = [];
    await runInBundleTransaction(async () => {
        deferUntilBundlesSettled(async () => {
            await Promise.resolve();
            calls.push("slow reaction finished");
        });
    });
    expect(calls).toEqual(["slow reaction finished"], {
        message: "loadBundle must not resolve before the reaction has run",
    });
});
