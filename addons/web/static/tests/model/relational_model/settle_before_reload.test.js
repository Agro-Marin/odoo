// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { EventBus } from "@odoo/owl";
import { ModelEvent } from "@web/core/events";
import { Mutex } from "@web/core/utils/concurrency";
import { RelationalModel } from "@web/model/relational_model/relational_model";

describe.current.tags("headless");

/** @returns {any} */
function makeModel() {
    const model = Object.create(RelationalModel.prototype);
    model.bus = new EventBus();
    model.mutex = new Mutex();
    model._compoundUpdates = new Set();
    model.config = { resModel: "res.partner" };
    return model;
}

describe("settleBeforeReload waits for everything _askChanges drains", () => {
    test("idle model: nothing to wait for", () => {
        const model = makeModel();
        expect(model.settleBeforeReload()).toBe(undefined);
    });

    test("mutex held: waits", () => {
        const model = makeModel();
        const held = model.mutex.exec(() => Promise.resolve());
        expect(model.mutex.locked).toBe(true);
        expect(model.settleBeforeReload()).not.toBe(undefined);
        return held;
    });

    test("compound cascade in flight with the mutex IDLE: waits", async () => {
        const model = makeModel();
        /** @type {(v?: any) => void} */
        let release = () => {};
        const gate = new Promise((resolve) => (release = resolve));
        const cascade = RelationalModel.prototype.trackCompoundUpdate.call(
            model,
            async () => {
                await gate;
            },
        );
        await Promise.resolve();
        await Promise.resolve();

        expect(model.mutex.locked).toBe(false, {
            message:
                "a cascade parked between two of its own awaits holds no lock — " +
                "which is exactly the window `Mutex.locked` cannot see",
        });
        expect(model._compoundUpdates.size).toBe(1);

        const settling = model.settleBeforeReload();
        expect(settling).not.toBe(undefined, {
            message:
                "the guard must cover both things `_askChanges` drains, or the " +
                "reload runs against a root the cascade is still writing to",
        });

        release();
        await settling;
        await cascade;
        expect(model._compoundUpdates.size).toBe(0);
    });

    test("the wait really drains the cascade, it does not just return a promise", async () => {
        const model = makeModel();
        let finished = false;
        /** @type {(v?: any) => void} */
        let release = () => {};
        const gate = new Promise((resolve) => (release = resolve));
        RelationalModel.prototype.trackCompoundUpdate.call(model, async () => {
            await gate;
            finished = true;
        });
        await Promise.resolve();
        await Promise.resolve();

        const settling = model.settleBeforeReload();
        release();
        await settling;
        expect(finished).toBe(true);
    });

    test("control: NEED_LOCAL_CHANGES is broadcast while settling", async () => {
        const model = makeModel();
        let asked = 0;
        model.bus.addEventListener(ModelEvent.NEED_LOCAL_CHANGES, () => asked++);
        RelationalModel.prototype.trackCompoundUpdate.call(model, async () => {});
        await model.settleBeforeReload();
        expect(asked).toBeGreaterThan(0, {
            message:
                "settling is what makes widgets flush their pending input; a " +
                "guard that returns early skips that too",
        });
    });
});
