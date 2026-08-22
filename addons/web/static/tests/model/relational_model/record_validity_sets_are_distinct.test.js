// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { MODEL_LIFECYCLE_PROTO } from "@web/../tests/model/relational_model/model_doubles";
import { makeActiveField } from "@web/model/relational_model/field_metadata";
import { RelationalRecord } from "@web/model/relational_model/record";

describe.current.tags("headless");

/**
 * @param {string} [name]
 */
function makeRecord(name = "") {
    const model = {
        Class: { Record: RelationalRecord },
        _patchConfig: (/** @type {any} */ config, /** @type {any} */ patch) =>
            Object.assign(config, patch),
        __proto__: MODEL_LIFECYCLE_PROTO,
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

        expect(record._checkValidity()).toBe(false);
        expect([...record._invalidFields]).toEqual(["name"]);
        expect([...record._unsetRequiredFields]).toEqual(["name"]);
    });

    test("a full pass does not clear a flag it does not own", () => {
        const record = makeRecord("filled");
        expect(record._checkValidity()).toBe(true);

        record._setInvalidFieldFlag("name");

        expect(record._checkValidity()).toBe(false, {
            message: "the widget's flag must survive a pass that found nothing",
        });
        expect([...record._invalidFields]).toEqual(["name"]);
        expect([...record._unsetRequiredFields]).toEqual([]);
    });
});
