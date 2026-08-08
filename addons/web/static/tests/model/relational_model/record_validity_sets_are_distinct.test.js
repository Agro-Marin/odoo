// @ts-check

/**
 * ``_invalidFields`` and ``_unsetRequiredFields`` look like a set and its
 * subset. They are not, and the difference is load-bearing.
 *
 * Instrumenting ``isValid`` to throw whenever ``_unsetRequiredFields`` held a
 * field ``_invalidFields`` did not, then running the model + fields + form +
 * list suites, produced 11 failures -- every one of them raised from
 * ``useInputField``'s ``onInput``, i.e. from a user typing into a required
 * field. That is ``resetFieldValidity`` doing its job: it drops the error
 * styling on the first keystroke by deleting from ``_invalidFields`` and
 * deliberately NOT from ``_unsetRequiredFields``, which belongs to the last
 * full validity pass rather than to the display.
 *
 * So "tidying" the two into one set, or making the second a subset of the
 * first, would either keep a field marked invalid while the user is fixing it
 * or lose the pass's record of which flags are its own to clear. This test
 * pins the whole cycle so that change fails here, with a reason.
 */

import { describe, expect, test } from "@odoo/hoot";
import { makeActiveField } from "@web/model/relational_model/field_metadata";
import { RelationalRecord } from "@web/model/relational_model/record";

describe.current.tags("headless");

/**
 * A real record with one required char field.
 *
 * @param {string} [name] its value; empty means required-and-unset
 */
function makeRecord(name = "") {
    const model = {
        Class: { Record: RelationalRecord },
        _patchConfig: (/** @type {any} */ config, /** @type {any} */ patch) =>
            Object.assign(config, patch),
        hooks: { lifecycle: { onWillSetInvalidField: () => {} }, ui: {} },
    };
    const config = {
        resModel: "line",
        activeFields: { name: makeActiveField({ required: true }) },
        fields: { name: { type: "char", name: "name" } },
        resId: 1,
        resIds: [1],
        isMonoRecord: true,
        mode: "edit",
        context: {},
    };
    return new RelationalRecord(
        /** @type {any} */ (model),
        /** @type {any} */ (config),
        { id: 1, name },
        {},
    );
}

describe("the two validity sets are distinct on purpose", () => {
    test("a full pass fills both; resetFieldValidity clears only the display one", () => {
        const record = makeRecord();

        expect(record._checkValidity()).toBe(false);
        expect([...record._invalidFields]).toEqual(["name"]);
        expect([...record._unsetRequiredFields]).toEqual(["name"]);

        // What onInput does on the first keystroke.
        record._resetFieldValidity("name");

        expect([...record._invalidFields]).toEqual([], {
            message: "the error styling must drop while the user is fixing it",
        });
        expect([...record._unsetRequiredFields]).toEqual(["name"], {
            message:
                "the pass's own record must survive, or the next pass cannot " +
                "tell its flags from a widget's",
        });
        expect(record.isValid).toBe(true, {
            message: "optimistically valid between the keystroke and the pass",
        });
    });

    test("the next full pass re-derives both, so an unfixed field is caught", () => {
        const record = makeRecord();
        record._checkValidity();
        record._resetFieldValidity("name");
        expect(record.isValid).toBe(true);

        // The save path always runs a full pass.
        expect(record._checkValidity()).toBe(false);
        expect([...record._invalidFields]).toEqual(["name"]);
        expect([...record._unsetRequiredFields]).toEqual(["name"]);
    });

    test("a full pass does not clear a flag it does not own", () => {
        const record = makeRecord("filled");
        expect(record._checkValidity()).toBe(true);

        // A widget rejects what was typed; the field is NOT required-unset.
        record._setInvalidFieldFlag("name");

        expect(record._checkValidity()).toBe(false, {
            message: "the widget's flag must survive a pass that found nothing",
        });
        expect([...record._invalidFields]).toEqual(["name"]);
        expect([...record._unsetRequiredFields]).toEqual([]);
    });
});
