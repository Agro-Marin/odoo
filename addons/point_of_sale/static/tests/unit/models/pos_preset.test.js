import { expect, test } from "@odoo/hoot";
import { luxon } from "@web/core/l10n/luxon";

import { definePosModels } from "../data/generate_model_definitions.js";
import { setupPosEnv } from "../utils.js";

const { DateTime } = luxon;

definePosModels();

test("generateSlots", async () => {
    const store = await setupPosEnv();
    const presetIn = store.models["pos.preset"].get(1);
    // expect all presetIn.availabilities to be empty slot maps (plain objects:
    // the previous Array-with-string-keys shape serialized to [] and lost
    // every slot)
    for (const key in presetIn.availabilities) {
        expect(Array.isArray(presetIn.availabilities[key])).toBe(false);
        expect(Object.keys(presetIn.availabilities[key]).length).toBe(0);
    }
    // expect days of week of presetOut.availabilities to contains slots
    const presetOut = store.models["pos.preset"].get(2);
    let daysWithSlot = 0;
    for (const key in presetOut.availabilities) {
        if (Object.keys(presetOut.availabilities[key]).length > 0) {
            daysWithSlot++;
            // each day should contains 23 slots of 20 minutes (12:00 to 15:00, and 18:00 to 22:00)
            expect(Object.keys(presetOut.availabilities[key]).length).toBe(23);
        }
    }
    // expect at least 5 days with slots (Monday to Friday)
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
    // The key must be the SQL-format string that generateSlots() looks up —
    // NOT the ISO string a DateTime coerces to when used directly as a key.
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
