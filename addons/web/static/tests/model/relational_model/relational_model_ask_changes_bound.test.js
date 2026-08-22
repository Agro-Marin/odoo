// @ts-check

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

        const ROUND_CAP = 500;
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
            rounds = ROUND_CAP;
            console.warn = originalWarn;
        }
        expect(warnings.length).toBe(1);
        expect(warnings[0]).toInclude("_askChanges");
        expect(warnings[0]).toInclude("res.partner");
        expect(roundsRun).toBeLessThan(ROUND_CAP);
    });
});
