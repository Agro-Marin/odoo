// @ts-check

/**
 * ``DynamicList.leaveEditMode`` contains two consecutive settle barriers::
 *
 *     if (editedRecord) { await this.model._askChanges(); }
 *     if (!discard && this.editedRecord) { await this.model._askChanges(); }
 *
 * The second one LOOKS like a copy-paste and is not: reactions from the first
 * flush settle in between, and a commit that failed validation must be
 * re-committed so it re-raises its invalid-field reaction. This file is the
 * only surviving home for that rationale — the call-site comment it used to
 * point at was deleted, and the bare duplicate reads as removable dead code.
 *
 * These pin the actual call counts, so removing a barrier is a visible,
 * deliberate change rather than a silent one.
 */

import { describe, expect, test } from "@odoo/hoot";
import { Mutex } from "@web/core/utils/concurrency";
import { DynamicList } from "@web/model/relational_model/dynamic_list";

describe.current.tags("headless");

/** @param {{ hasEditedRecord: boolean }} options */
function makeList({ hasEditedRecord }) {
    const list = Object.create(DynamicList.prototype);
    let askChangesCalls = 0;
    const record = {
        isInEdition: true,
        isNew: false,
        dirty: false,
        _checkValidity: () => true,
        _save: async () => true,
        _discard() {},
        config: {},
        id: "rec_1",
    };
    list._records = hasEditedRecord ? [record] : [];
    Object.defineProperty(list, "records", { get: () => list._records });
    list._removeRecords = () => {};
    list.model = {
        urgentSave: { isActive: false },
        mutex: new Mutex(),
        closeUrgentSaveNotification() {},
        _askChanges: async () => {
            askChangesCalls++;
        },
        _patchConfig: (/** @type {any} */ config, /** @type {any} */ patch) =>
            Object.assign(config, patch),
    };
    return { list, counts: () => askChangesCalls };
}

describe("leaveEditMode settle barriers", () => {
    test("the save path runs the barrier TWICE for one leave", async () => {
        const { list, counts } = makeList({ hasEditedRecord: true });
        await list.leaveEditMode();
        expect(counts()).toBe(2);
    });

    test("the discard path runs it once", async () => {
        const { list, counts } = makeList({ hasEditedRecord: true });
        await list.leaveEditMode({ discard: true });
        expect(counts()).toBe(1);
    });

    test("with no row in edition it never runs", async () => {
        const { list, counts } = makeList({ hasEditedRecord: false });
        await list.leaveEditMode();
        expect(counts()).toBe(0);
    });
});
