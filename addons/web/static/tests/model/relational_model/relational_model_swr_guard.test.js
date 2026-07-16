// @ts-check

/**
 * Unit tests for the stale-while-revalidate cache callback guard
 * (``RelationalModel._getCacheParams``): a background revalidation must not
 * rebuild the root's record datapoints (``root._setData``) while a record is
 * being edited, has unsaved changes, or is SELECTED — the rebuild would wipe
 * that state (e.g. checked rows losing their selection under a bulk-action
 * click).
 *
 * Uses ``Object.create(RelationalModel.prototype)`` with hand-built state.
 */

import { describe, expect, test } from "@odoo/hoot";
import { RelationalModel } from "@web/model/relational_model/relational_model";

function makeModelWithRoot(records) {
    const model = Object.create(RelationalModel.prototype);
    model.withCache = true;
    model.isReady = false; // first load → cache params returned
    model.sampleData = { isActive: false };
    const setDataCalls = [];
    const root = {
        id: "root_dp",
        config: {
            isMonoRecord: false,
            groupBy: [],
            loadId: "load_1",
            resId: undefined,
        },
        records,
        _setData: (result) => setDataCalls.push(result),
    };
    model.root = root;
    const rootLoadDef = Promise.resolve({ root, loadId: "load_1" });
    const cacheParams = model._getCacheParams(
        { isMonoRecord: false, resId: undefined },
        rootLoadDef,
    );
    return { model, root, cacheParams, setDataCalls };
}

function makeMonoModelWithRoot({ resId = 5, loadId = "load_1" } = {}) {
    const model = Object.create(RelationalModel.prototype);
    model.withCache = true;
    model.isReady = false; // first load → cache params returned
    model.sampleData = { isActive: false };
    const setDataCalls = [];
    const root = {
        id: "root_dp",
        config: {
            isMonoRecord: true,
            groupBy: [],
            loadId,
            resId,
        },
        _setData: (result) => setDataCalls.push(result),
    };
    model.root = root;
    const rootLoadDef = Promise.resolve({ root, loadId });
    const cacheParams = model._getCacheParams(
        { isMonoRecord: true, resId },
        rootLoadDef,
    );
    return { model, root, cacheParams, setDataCalls };
}

describe("SWR revalidation guard", () => {
    test("a fresh result rebuilds a clean, unselected root", async () => {
        const { cacheParams, setDataCalls } = makeModelWithRoot([
            { isInEdition: false, dirty: false, selected: false },
        ]);

        await cacheParams.callback({ records: [], length: 0 }, true);

        expect(setDataCalls.length).toBe(1);
    });

    test("selected records block the rebuild", async () => {
        const { cacheParams, setDataCalls } = makeModelWithRoot([
            { isInEdition: false, dirty: false, selected: false },
            { isInEdition: false, dirty: false, selected: true },
        ]);

        await cacheParams.callback({ records: [], length: 0 }, true);

        expect(setDataCalls.length).toBe(0);
    });

    test("dirty and edited records still block the rebuild", async () => {
        const dirty = makeModelWithRoot([
            { isInEdition: false, dirty: true, selected: false },
        ]);
        await dirty.cacheParams.callback({ records: [], length: 0 }, true);
        expect(dirty.setDataCalls.length).toBe(0);

        const edited = makeModelWithRoot([
            { isInEdition: true, dirty: false, selected: false },
        ]);
        await edited.cacheParams.callback({ records: [], length: 0 }, true);
        expect(edited.setDataCalls.length).toBe(0);
    });

    test("an unchanged result is a no-op", async () => {
        const { cacheParams, setDataCalls } = makeModelWithRoot([
            { isInEdition: false, dirty: false, selected: false },
        ]);

        await cacheParams.callback({ records: [], length: 0 }, false);

        expect(setDataCalls.length).toBe(0);
    });

    test("a mono-record revalidation rebuilds while loadId still matches", async () => {
        // Baseline: no save happened, the captured loadId matches the root's,
        // so a changed revalidation legitimately refreshes the record.
        const { cacheParams, setDataCalls } = makeMonoModelWithRoot();

        await cacheParams.callback([{ id: 5, foo: "fresh" }], true);

        expect(setDataCalls).toEqual([{ id: 5, foo: "fresh" }]);
    });

    test("a mono-record revalidation is discarded after a save bumped loadId", async () => {
        // Regression for the silent post-save revert: a cache-hit render kicks
        // off a background web_read whose response reflects PRE-save data. A
        // successful save bumps the root config.loadId (record_save.js), so the
        // stale revalidation must fail the loadId guard and NOT _setData the
        // saved values back to their pre-save state.
        const { root, cacheParams, setDataCalls } = makeMonoModelWithRoot();

        root.config.loadId = "load_2"; // save bumped it after the read was issued
        await cacheParams.callback([{ id: 5, foo: "stale-pre-save" }], true);

        expect(setDataCalls.length).toBe(0);
    });
});
