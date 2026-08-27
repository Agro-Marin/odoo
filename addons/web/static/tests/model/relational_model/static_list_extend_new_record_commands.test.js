// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { makeActiveField } from "@web/model/relational_model/field_metadata";
import { ListMembership } from "@web/model/relational_model/list_membership";
import { StaticList } from "@web/model/relational_model/static_list";

describe.current.tags("headless");

function makeList() {
    /** @type {any[]} */
    const applied = [];
    const list = Object.create(StaticList.prototype);
    Object.assign(list, {
        _membership: new ListMembership(),
        _config: {
            activeFields: { display_name: makeActiveField() },
            fields: { display_name: { type: "char", name: "display_name" } },
            resModel: "res.partner",
            context: {},
        },
        _extendedRecords: new Set(),
        _unknownRecordCommands: new Map(),
        model: {
            mutex: { exec: (/** @type {() => any} */ fn) => fn() },
            _patchConfig: (/** @type {any} */ config, /** @type {any} */ patch) =>
                Object.assign(config, patch),
        },
    });
    list._applyCommands = async (/** @type {any[]} */ commands) => {
        applied.push(...commands);
    };
    return { list, applied };
}

/**
 * @param {{ resId: number | false, virtualId: string | false }} ids
 */
function makeRecord({ resId, virtualId }) {
    return {
        id: "datapoint_1",
        resId,
        _virtualId: virtualId,
        isNew: !resId,
        config: {
            activeFields: { display_name: makeActiveField() },
            fields: { display_name: { type: "char", name: "display_name" } },
        },
        activeFields: {},
        data: {},
        _addSavePoint() {},
        _applyDefaultValues() {},
        _applyValues() {},
        extendActiveFields() {},
    };
}

const PARAMS = {
    activeFields: { display_name: makeActiveField() },
    fields: { display_name: { type: "char", name: "display_name" } },
};

describe("extendRecord replays the commands parked for the row", () => {
    test("a new record: parked under its virtual id", async () => {
        const { list, applied } = makeList();
        const record = makeRecord({ resId: false, virtualId: "virtual_7" });
        list._unknownRecordCommands.set("virtual_7", [[1, "virtual_7", { a: 1 }]]);

        await list.extendRecord(PARAMS, /** @type {any} */ (record));

        expect(applied).toEqual([[1, "virtual_7", { a: 1 }]]);
        expect(list._unknownRecordCommands.has("virtual_7")).toBe(false);
    });

    test("a saved record: parked under its resId", async () => {
        const { list, applied } = makeList();
        const record = makeRecord({ resId: 42, virtualId: false });
        list._unknownRecordCommands.set(42, [[1, 42, { a: 2 }]]);
        list.model._loadRecords = async () => [{ id: 42 }];

        await list.extendRecord(PARAMS, /** @type {any} */ (record));

        expect(applied).toEqual([[1, 42, { a: 2 }]]);
        expect(list._unknownRecordCommands.has(42)).toBe(false);
    });

    test("nothing parked: nothing replayed", async () => {
        const { list, applied } = makeList();
        const record = makeRecord({ resId: false, virtualId: "virtual_9" });

        await list.extendRecord(PARAMS, /** @type {any} */ (record));

        expect(applied).toEqual([]);
    });
});
