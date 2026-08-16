// @ts-check

/**
 * ``fromUnityToServerValues`` converts server-originated payloads (onchange
 * commands for records the client never loaded) into write format. It already
 * treats an unknown FIELD as non-fatal — the payload names the server's field
 * universe, not this view's — but it dereferenced ``activeFields[name]``
 * unguarded, and the two sets are not the same size:
 * ``extractFieldsFromArchInfo`` returns the view's FULL field set as ``fields``
 * while ``activeFields`` holds only what the arch mentions.
 *
 * The gap is reachable, not theoretical: the command engine's UPDATE case
 * deliberately stashes an x2many slice when ``!(fieldName in
 * record.activeFields)`` ("this record hasn't been extended"), and
 * ``serializeCommands`` later feeds exactly that stash back through here. A
 * nested CREATE/UPDATE then hit ``activeField.related.fields`` on ``undefined``
 * and threw during save.
 */

import { describe, expect, test } from "@odoo/hoot";
import { x2ManyCommands } from "@web/core/network/commands";
import { fromUnityToServerValues } from "@web/model/relational_model/field_values";

describe.current.tags("headless");

const FIELDS = {
    name: { name: "name", type: "char" },
    // Present on the model, absent from the arch — so absent from activeFields.
    tag_ids: { name: "tag_ids", type: "many2many", relation: "tag" },
    line_ids: { name: "line_ids", type: "one2many", relation: "line" },
};

describe("fromUnityToServerValues with no matching activeField", () => {
    test("an x2many CREATE for a non-arch field does not throw", () => {
        const values = {
            tag_ids: [x2ManyCommands.create(false, { name: "new tag" })],
        };
        const out = fromUnityToServerValues(
            values,
            FIELDS,
            {},
            {
                withReadonly: true,
            },
        );
        expect(out.tag_ids).toEqual(values.tag_ids);
    });

    test("an x2many UPDATE for a non-arch field does not throw", () => {
        const values = { line_ids: [x2ManyCommands.update(7, { name: "x" })] };
        const out = fromUnityToServerValues(
            values,
            FIELDS,
            {},
            {
                withReadonly: true,
            },
        );
        expect(out.line_ids).toEqual(values.line_ids);
    });

    test("commands needing no sub-schema are still normalised", () => {
        const values = {
            tag_ids: [[x2ManyCommands.LINK, 3, { id: 3, display_name: "T" }]],
        };
        const out = fromUnityToServerValues(
            values,
            FIELDS,
            {},
            {
                withReadonly: true,
            },
        );
        // The LINK payload is dropped exactly as it is for an arch field.
        expect(out.tag_ids).toEqual([[x2ManyCommands.LINK, 3, false]]);
    });

    test("a scalar with no activeField is still converted by type", () => {
        const out = fromUnityToServerValues(
            { name: "hello" },
            FIELDS,
            {},
            { withReadonly: true },
        );
        expect(out.name).toBe("hello");
    });

    test("the readonly gate does not throw without an activeField", () => {
        // withReadonly omitted -> the readonly branch runs.
        const out = fromUnityToServerValues({ name: "hello" }, FIELDS, {}, {});
        expect(out.name).toBe("hello");
    });

    test("an arch field still recurses through its related schema", () => {
        const activeFields = {
            line_ids: {
                readonly: "False",
                related: {
                    fields: { partner_id: { name: "partner_id", type: "many2one" } },
                    activeFields: { partner_id: { readonly: "False" } },
                },
            },
        };
        const values = {
            line_ids: [
                x2ManyCommands.update(7, {
                    partner_id: { id: 4, display_name: "P" },
                }),
            ],
        };
        const out = fromUnityToServerValues(values, FIELDS, activeFields, {
            withReadonly: true,
        });
        // many2one collapsed to its id by the recursive call.
        expect(out.line_ids).toEqual([[x2ManyCommands.UPDATE, 7, { partner_id: 4 }]]);
    });
});
