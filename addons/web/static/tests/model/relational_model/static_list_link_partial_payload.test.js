// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { x2ManyCommands } from "@web/core/network/commands";
import { makeActiveField } from "@web/model/relational_model/field_metadata";
import { RelationalRecord } from "@web/model/relational_model/record";
import { StaticList } from "@web/model/relational_model/static_list";

const SERVER = {
    5: { id: 5, name: "five", note: "N5" },
    6: { id: 6, name: "six", note: "N6" },
};

function makeList() {
    /** @type {any[]} */
    const requested = [];
    const model = {
        Class: { Record: RelationalRecord, StaticList },
        _patchConfig: (/** @type {any} */ config, /** @type {any} */ patch) =>
            Object.assign(config, patch),
        _loadRecords: async (/** @type {any} */ { resIds }) => {
            requested.push([...resIds]);
            return resIds.map((/** @type {number} */ id) => ({
                .../** @type {Record<number, any>} */ (SERVER)[id],
            }));
        },
    };
    const config = {
        resModel: "line",
        activeFields: { name: makeActiveField(), note: makeActiveField() },
        fields: {
            name: { type: "char", name: "name" },
            note: { type: "char", name: "note" },
        },
        relationField: false,
        offset: 0,
        limit: 80,
        resIds: /** @type {any[]} */ ([]),
        orderBy: /** @type {any[]} */ ([]),
        context: {},
    };
    const list = new StaticList(
        /** @type {any} */ (model),
        /** @type {any} */ (config),
        [],
        {
            parent: {
                evalContext: {},
                evalContextWithVirtualIds: {},
                _isEvalContextReady: true,
            },
            onUpdate: async () => {},
        },
    );
    return { list, requested };
}

describe("a LINK payload is authoritative", () => {
    test("a BARE link is completed by a read", async () => {
        const { list, requested } = makeList();

        await list._applyCommands([[x2ManyCommands.LINK, 6, false]]);

        expect(requested).toEqual([[6]]);
        expect(/** @type {any} */ (list._cache).get(6).data.note).toBe("N6");
    });

    test("a COMPLETE payload costs no round trip", async () => {
        const { list, requested } = makeList();

        await list._applyCommands([
            [x2ManyCommands.LINK, 5, { name: "five", note: "N5" }],
        ]);

        expect(requested).toEqual([]);
        expect(/** @type {any} */ (list._cache).get(5).data.note).toBe("N5");
    });

    test("a PARTIAL payload is trusted, NOT completed", async () => {
        const { list, requested } = makeList();

        await list._applyCommands([[x2ManyCommands.LINK, 5, { name: "five" }]]);

        expect(requested).toEqual([]);
        expect(/** @type {any} */ (list._cache).get(5).data.note).toBe("");
        expect(
            [.../** @type {any} */ (list._cache).get(5)._loadedFieldNames].sort(),
        ).toEqual(["id", "name"]);
    });

    test("an already fully cached row is not re-read", async () => {
        const { list, requested } = makeList();
        await list._applyCommands([[x2ManyCommands.LINK, 5, false]]);
        expect(requested).toEqual([[5]]);
        await list._applyCommands([[x2ManyCommands.UNLINK, 5, false]]);
        requested.length = 0;

        await list._applyCommands([[x2ManyCommands.LINK, 5, false]]);

        expect(requested).toEqual([]);
        expect(/** @type {any} */ (list._cache).get(5).data.note).toBe("N5");
    });
});
