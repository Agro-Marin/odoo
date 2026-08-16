// @ts-check

/**
 * What a LINK command's third slot means, pinned.
 *
 * A LINK may carry no inlined values, all of them, or only some:
 *
 *  - ``x2ManyCommands.link(id)`` emits ``[4, id, false]``;
 *  - an onchange may return a LINK with the sub-record's values inlined;
 *  - ``DynamicList._multiSave`` rewrites a many2many's LINKs to carry ONLY
 *    ``display_name``, and applies them to every other selected record's list.
 *
 * The contract is that a payload is AUTHORITATIVE -- the sender decided what
 * the row needs -- so only a BARE link is completed by a webRead. Treating a
 * partial payload as incomplete and reading the difference is not a free
 * improvement: it re-reads the whole tag list on any many2many_tags edit, which
 * is why the third test below exists.
 *
 * The known sharp edge: a payload that omits a field the list actually renders
 * leaves that field at its default, and nothing queues a read. No in-repo
 * sender does this -- the omissions are all fields the view does not show.
 */

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
        expect(/** @type {Record<string, any>} */ (list._cache)[6].data.note).toBe(
            "N6",
        );
    });

    test("a COMPLETE payload costs no round trip", async () => {
        const { list, requested } = makeList();

        await list._applyCommands([
            [x2ManyCommands.LINK, 5, { name: "five", note: "N5" }],
        ]);

        expect(requested).toEqual([]);
        expect(/** @type {Record<string, any>} */ (list._cache)[5].data.note).toBe(
            "N5",
        );
    });

    test("a PARTIAL payload is trusted, NOT completed", async () => {
        // The sharp edge, asserted so a change to it is a deliberate act:
        // `note` settles at its default because nothing re-reads the row.
        // Completing it here would re-read every tag on a many2many_tags edit.
        const { list, requested } = makeList();

        await list._applyCommands([[x2ManyCommands.LINK, 5, { name: "five" }]]);

        expect(requested).toEqual([]);
        expect(/** @type {Record<string, any>} */ (list._cache)[5].data.note).toBe("");
        expect(
            [
                .../** @type {Record<string, any>} */ (list._cache)[5]
                    ._loadedFieldNames,
            ].sort(),
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
        expect(/** @type {Record<string, any>} */ (list._cache)[5].data.note).toBe(
            "N5",
        );
    });
});
