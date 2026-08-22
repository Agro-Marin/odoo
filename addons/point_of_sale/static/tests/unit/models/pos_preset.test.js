import { expect, test } from "@odoo/hoot";
import { luxon } from "@web/core/l10n/luxon";

import { definePosModels } from "../data/generate_model_definitions.js";
import { setupPosEnv } from "../utils.js";

const { DateTime } = luxon;

definePosModels();

test("generateSlots", async () => {
    const store = await setupPosEnv();
    const presetIn = store.models["pos.preset"].get(1);
    for (const key in presetIn.availabilities) {
        expect(Array.isArray(presetIn.availabilities[key])).toBe(false);
        expect(Object.keys(presetIn.availabilities[key]).length).toBe(0);
    }
    const presetOut = store.models["pos.preset"].get(2);
    let daysWithSlot = 0;
    for (const key in presetOut.availabilities) {
        if (Object.keys(presetOut.availabilities[key]).length > 0) {
            daysWithSlot++;
            expect(Object.keys(presetOut.availabilities[key]).length).toBe(23);
        }
    }
    expect(daysWithSlot).toBe(5);
});

test("slotsUsage keys local orders by SQL datetime, not the DateTime's ISO string", async () => {
    const store = await setupPosEnv();
    const preset = store.models["pos.preset"].get(2);
    const presetTime = DateTime.fromObject({
        year: 2026,
        month: 7,
        day: 17,
        hour: 12,
        minute: 20,
        second: 0,
    });
    const order = store.models["pos.order"].create({
        preset_id: preset,
        preset_time: presetTime,
    });

    const usage = preset.slotsUsage;
    const sqlKey = presetTime.toFormat("yyyy-MM-dd HH:mm:ss");
    expect(usage[sqlKey]).toEqual([order.id]);
    expect(Object.keys(usage)).toEqual([sqlKey]);
    expect(usage[presetTime.toISO()]).toBe(undefined);
});

test("slotsUsage skips orders without a preset_time", async () => {
    const store = await setupPosEnv();
    const preset = store.models["pos.preset"].get(2);
    store.models["pos.order"].create({ preset_id: preset });
    expect(preset.slotsUsage).toEqual({});
});
