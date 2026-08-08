// @ts-check

/**
 * ``getAggregateSpecifications`` memoises per (field container, requested
 * subset).
 *
 * The read-group REQUEST asks only for ``config.fieldsToAggregate`` while the
 * RESPONSE is decoded against the whole ``config.fields``. That used to be
 * expressed by handing the request side a ``pick()`` of the fields — a fresh
 * object on every call, so the ``WeakMap`` keyed on it could never hit and
 * every read-group rebuilt the spec list from scratch. The subset is now a
 * second cache level keyed on the field NAMES, which is what makes it stable:
 * ``kanban_controller`` rebuilds ``fieldsToAggregate`` with ``.map()`` for each
 * config, so an identity key would miss just as reliably.
 */

import { describe, expect, test } from "@odoo/hoot";
import { getAggregateSpecifications } from "@web/model/relational_model/field_values";

describe.current.tags("headless");

function makeFields() {
    return {
        amount: { name: "amount", type: "monetary", aggregator: "sum" },
        currency_id: { name: "currency_id", type: "many2one" },
        qty: { name: "qty", type: "integer", aggregator: "sum" },
        name: { name: "name", type: "char" },
        untracked: { name: "untracked", type: "integer" },
    };
}

describe("getAggregateSpecifications", () => {
    test("scoping to field names matches picking those fields first", () => {
        const fields = makeFields();
        const names = ["amount", "qty", "name"];

        const scoped = getAggregateSpecifications(fields, names);
        // what the call site used to do: pick(fields, ...names)
        const picked = getAggregateSpecifications(
            Object.fromEntries(
                names.map((n) => [n, /** @type {Record<string, any>} */ (fields)[n]]),
            ),
        );

        expect(scoped).toEqual(picked);
        expect(scoped).toEqual(["amount:sum", "qty:sum"]);
    });

    test("monetary fields still pull in their currency companions", () => {
        const fields = makeFields();
        fields.amount.currency_field = "currency_id";

        expect(getAggregateSpecifications(fields, ["amount"])).toEqual([
            "amount:sum",
            "currency_id:array_agg_distinct",
            "amount:sum_currency",
        ]);
    });

    test("a value-equal name list hits the cache, a different one does not", () => {
        const fields = makeFields();

        const first = getAggregateSpecifications(fields, ["amount", "qty"]);
        // a distinct array with the same names — the shape kanban_controller
        // produces on every config rebuild
        const second = getAggregateSpecifications(fields, ["amount", "qty"]);
        expect(second).toBe(first);

        const narrower = getAggregateSpecifications(fields, ["qty"]);
        expect(narrower).not.toBe(first);
        expect(narrower).toEqual(["qty:sum"]);

        // the unscoped (response-decoding) scope is cached independently
        const all = getAggregateSpecifications(fields);
        expect(all).not.toBe(first);
        expect(all).toEqual(["amount:sum", "qty:sum"]);
        expect(getAggregateSpecifications(fields)).toBe(all);
    });

    test("duplicate and unknown names are ignored, as pick() did", () => {
        const fields = makeFields();

        expect(getAggregateSpecifications(fields, ["qty", "qty", "nope"])).toEqual([
            "qty:sum",
        ]);
    });
});

describe("scope key isolation", () => {
    test("an empty scope does not share the all-fields cache slot", () => {
        // A grouped kanban whose progressbar carries no ``sum_field`` passes
        // exactly this empty scope: ``kanban_controller``'s
        // ``progressBarAggregateFields`` is then ``[]``, and it lands on the
        // same long-lived ``config.fields`` that the response decoding reads
        // back with no scope at all. A bare ``join(",")`` made both key on
        // ``""``, so whichever ran first answered for the other.
        const fields = makeFields();

        expect(getAggregateSpecifications(fields, [])).toEqual([]);
        expect(getAggregateSpecifications(fields)).toEqual(["amount:sum", "qty:sum"]);
    });

    test("the collision is absent in the reverse order too", () => {
        const fields = makeFields();

        expect(getAggregateSpecifications(fields)).toEqual(["amount:sum", "qty:sum"]);
        expect(getAggregateSpecifications(fields, [])).toEqual([]);
    });
});
