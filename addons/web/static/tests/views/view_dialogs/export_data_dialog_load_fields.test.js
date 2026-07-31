// @ts-check

/**
 * @module tests/views/view_dialogs/export_data_dialog_load_fields
 *
 * ``ExportDataDialog.loadFields`` feeds two things at once: the tree rendered
 * by ``ExportDataItem`` (its return value) and the ``knownFields`` map that
 * ``onAddItemExportList`` resolves an id against. Handing back fields that were
 * never registered breaks that pairing: adding one resolves
 * ``knownFields[id]`` to ``undefined``, pushes it into ``exportList``, and the
 * download then dereferences ``field.name`` on it.
 */

import { describe, expect, test } from "@odoo/hoot";
import { ExportDataDialog } from "@web/views/view_dialogs/export_data_dialog";

describe.current.tags("headless");

/** Minimal `this` for the method under test. */
function makeContext({ onFetch } = {}) {
    const ctx = {
        knownFields: {
            partner_id: {
                id: "partner_id",
                string: "Partner",
                params: {},
                field_type: "many2one",
                relation_field: "x",
            },
        },
        expandedFields: {},
        state: { isCompatible: false },
        props: {
            getExportedFields: async () => {
                onFetch?.(ctx);
                return [{ id: "partner_id/name", string: "Name" }];
            },
        },
    };
    return ctx;
}

describe("loadFields", () => {
    test("registers every field it returns", async () => {
        const ctx = makeContext();
        const fields = await ExportDataDialog.prototype.loadFields.call(
            ctx,
            "partner_id",
            false,
        );
        for (const field of fields) {
            expect(ctx.knownFields[field.id]).toBe(field);
        }
        expect(ctx.expandedFields["partner_id"].fields).toBe(fields);
    });

    test("returns nothing when superseded by a compatibility toggle", async () => {
        // The toggle lands while the fetch is in flight: the whole tree is
        // about to be rebuilt, so there is no valid subtree to hand back.
        const ctx = makeContext({
            onFetch: (c) => {
                c.state.isCompatible = true;
            },
        });
        const fields = await ExportDataDialog.prototype.loadFields.call(
            ctx,
            "partner_id",
            false,
        );
        expect(fields).toBe(undefined);
        expect("partner_id/name" in ctx.knownFields).toBe(false);
    });

    test("serves the cached expansion without refetching", async () => {
        const ctx = makeContext();
        ctx.expandedFields["partner_id"] = { fields: [{ id: "cached" }] };
        let fetched = false;
        ctx.props.getExportedFields = async () => {
            fetched = true;
            return [];
        };
        const fields = await ExportDataDialog.prototype.loadFields.call(
            ctx,
            "partner_id",
            false,
        );
        expect(fetched).toBe(false);
        expect(fields.map((f) => f.id)).toEqual(["cached"]);
    });

    test("preventLoad returns nothing and issues no fetch", async () => {
        const ctx = makeContext();
        let fetched = false;
        ctx.props.getExportedFields = async () => {
            fetched = true;
            return [];
        };
        const fields = await ExportDataDialog.prototype.loadFields.call(
            ctx,
            "partner_id",
            true,
        );
        expect(fields).toBe(undefined);
        expect(fetched).toBe(false);
    });
});
