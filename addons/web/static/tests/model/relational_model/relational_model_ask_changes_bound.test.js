// @ts-check

/**
 * ``RelationalModel._askChanges`` settles pending edits in rounds and used to
 * loop ``while (true)``. A widget that re-opens a compound update on every
 * round therefore hung the barrier — and with it every ``save`` /
 * ``leaveEditMode`` / ``load`` waiting behind it — with nothing in the console.
 * It must degrade the way ``record_save.waitForPendingCommands`` does: warn,
 * then proceed.
 */

import { describe, expect, test } from "@odoo/hoot";
import { EventBus } from "@odoo/owl";
import { ModelEvent } from "@web/core/events";
import { Mutex } from "@web/core/utils/concurrency";
import { RelationalModel } from "@web/model/relational_model/relational_model";

function makeModel() {
    const model = Object.create(RelationalModel.prototype);
    model.bus = new EventBus();
    model.mutex = new Mutex();
    model._compoundUpdates = new Set();
    model.config = { resModel: "res.partner" };
    return model;
}

describe("_askChanges settle loop", () => {
    test("returns once nothing is left in flight", async () => {
        const model = makeModel();
        let rounds = 0;
        model.bus.addEventListener(ModelEvent.NEED_LOCAL_CHANGES, () => rounds++);
        await model._askChanges();
        expect(rounds).toBe(1);
        expect(model._compoundUpdates.size).toBe(0);
    });

    test("drains a real multi-step cascade", async () => {
        const model = makeModel();
        let depth = 2;
        model.bus.addEventListener(ModelEvent.NEED_LOCAL_CHANGES, () => {
            if (depth-- > 0) {
                RelationalModel.prototype.trackCompoundUpdate.call(
                    model,
                    async () => {},
                );
            }
        });
        await model._askChanges();
        expect(model._compoundUpdates.size).toBe(0);
    });

    test("gives up with a warning instead of hanging on a looping widget", async () => {
        const model = makeModel();
        /** @type {string[]} */
        const warnings = [];
        const originalWarn = console.warn;
        console.warn = (msg) => warnings.push(String(msg));

        // The pathological shape: each compound update opens the next one from
        // its own continuation, so every settle round finds a fresh unit and
        // the set is never observed empty.
        //
        // The escape hatch is keyed on ROUNDS, not on spawns. A spawn cap does
        // not work: the chain advances once per microtask while a round costs
        // only a handful of them, so it burns through any spawn budget within a
        // few rounds and ``_askChanges`` then returns via the normal
        // empty-set path — passing whether or not the bound exists.
        //
        // A cap is needed at all because the unbounded loop is a pure microtask
        // chain that never yields to the macrotask queue: hoot's per-test
        // timeout cannot fire, and the browser allocates until the runner is
        // OOM-killed, taking the whole suite with it instead of failing here.
        const ROUND_CAP = 500; // 5x the model's own bound
        let rounds = 0;
        const spawn = () =>
            RelationalModel.prototype.trackCompoundUpdate.call(model, async () => {
                if (rounds < ROUND_CAP) {
                    spawn();
                }
            });
        model.bus.addEventListener(ModelEvent.NEED_LOCAL_CHANGES, () => {
            rounds++;
            spawn();
        });

        let roundsRun;
        try {
            await model._askChanges();
            roundsRun = rounds;
        } finally {
            rounds = ROUND_CAP; // stop the chain
            console.warn = originalWarn;
        }
        expect(warnings.length).toBe(1);
        expect(warnings[0]).toInclude("_askChanges");
        expect(warnings[0]).toInclude("res.partner");
        // Gave up at its own bound, well short of the test's escape hatch.
        expect(roundsRun).toBeLessThan(ROUND_CAP);
    });
});
