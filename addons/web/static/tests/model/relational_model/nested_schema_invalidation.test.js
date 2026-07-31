// @ts-check

/**
 * Two memos are keyed on mutable containers: the modifier-dependency map
 * (``record_utils``, keyed on an ``activeFields`` object) and the aggregate
 * specs (``field_values``, keyed on a ``fields`` object). Both containers are
 * mutated IN PLACE by the arch-merge helpers, including at NESTED levels — an
 * x2many's ``related.activeFields`` / ``related.fields`` are the ``config``
 * containers of the nested StaticList and its sub-records.
 *
 * The invalidation used to live at the call site (``static_list.extendRecord``),
 * which only knew about the TOP level, so a form arch adding a field to a
 * nested x2many left that level's memo describing the pre-merge schema — and
 * the scoped re-validation missed the new field's modifier dependencies. It now
 * lives inside the helpers that do the mutating, which is what these tests pin.
 */

import { describe, expect, test } from "@odoo/hoot";
import {
    completeActiveFields,
    makeActiveField,
    patchActiveFields,
} from "@web/model/relational_model/field_metadata";
import { getAggregateSpecifications } from "@web/model/relational_model/field_values";
import { getModifierDependencies } from "@web/model/relational_model/record_utils";

describe.current.tags("headless");

/** An x2many activeField whose ``related`` containers stand in for a nested list's config. */
function makeX2manyActiveField() {
    return {
        ...makeActiveField(),
        related: {
            activeFields: { qty: makeActiveField() },
            fields: { qty: { type: "integer", name: "qty" } },
        },
    };
}

describe("patchActiveFields", () => {
    test("invalidates the nested modifier-dependency memo", () => {
        const activeField = makeX2manyActiveField();
        const nested = activeField.related.activeFields;
        // prime the memo against the pre-merge schema
        expect(getModifierDependencies(nested).dependents.get("qty")).toBe(undefined);

        patchActiveFields(activeField, {
            ...makeActiveField(),
            related: {
                activeFields: { name: makeActiveField({ required: "qty > 0" }) },
                fields: { name: { type: "char", name: "name" } },
            },
        });

        const deps = getModifierDependencies(nested);
        expect([...(deps.dependents.get("qty") || [])]).toEqual(["name"]);
    });

    test("invalidates the nested aggregate-spec memo", () => {
        const activeField = makeX2manyActiveField();
        const nestedFields = activeField.related.fields;
        expect(getAggregateSpecifications(nestedFields)).toEqual([]);

        patchActiveFields(activeField, {
            ...makeActiveField(),
            related: {
                activeFields: { total: makeActiveField() },
                fields: {
                    total: { type: "float", name: "total", aggregator: "sum" },
                },
            },
        });

        expect(getAggregateSpecifications(nestedFields)).toEqual(["total:sum"]);
    });
});

describe("completeActiveFields", () => {
    test("invalidates the top-level and nested modifier-dependency memos", () => {
        const listActiveFields = { line_ids: makeX2manyActiveField() };
        const nested = listActiveFields.line_ids.related.activeFields;
        expect(getModifierDependencies(listActiveFields).dependents.size).toBe(0);
        expect(getModifierDependencies(nested).dependents.get("qty")).toBe(undefined);

        completeActiveFields(listActiveFields, {
            line_ids: {
                ...makeActiveField(),
                related: {
                    activeFields: { name: makeActiveField({ required: "qty > 0" }) },
                    fields: { name: { type: "char", name: "name" } },
                },
            },
            state: makeActiveField(),
            // NOT ``invisible``: completeActiveFields forces that to "True" for
            // fields the list did not have, which would erase the reference.
            extra: makeActiveField({ required: "state == 'done'" }),
        });

        expect([
            ...(getModifierDependencies(nested).dependents.get("qty") || []),
        ]).toEqual(["name"]);
        expect([
            ...(getModifierDependencies(listActiveFields).dependents.get("state") ||
                []),
        ]).toEqual(["extra"]);
    });
});
