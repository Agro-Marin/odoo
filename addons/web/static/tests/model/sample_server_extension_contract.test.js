// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { MAX_FLOAT, MAX_INTEGER } from "@web/model/sample_data";
import { SampleServer } from "@web/model/sample_server";

describe.current.tags("headless");

const FIELDS = {
    id: { string: "ID", type: "integer" },
    display_name: { string: "Name", type: "char" },
    unit_amount: { string: "Amount", type: "float", aggregator: "sum" },
    quantity: { string: "Qty", type: "integer", aggregator: "sum" },
};

/** @returns {any} */
function makeServer() {
    return new SampleServer("some.model", { ...FIELDS });
}

test("_generateFieldValue resolves the field from (modelName, fieldName)", () => {
    const server = makeServer();

    const amount = server._generateFieldValue("some.model", "unit_amount");
    expect(typeof amount).toBe("number");
    expect(amount).toBeGreaterThan(-1);
    expect(amount).toBeLessThan(MAX_FLOAT);

    const qty = server._generateFieldValue("some.model", "quantity");
    expect(Number.isInteger(qty)).toBe(true);
    expect(qty).toBeLessThan(MAX_INTEGER);
});

test("_generateFieldValue still honours id when given (the populate path)", () => {
    const server = makeServer();
    expect(server._generateFieldValue("some.model", "display_name", 1)).toBe(
        server._generateFieldValue("some.model", "display_name", 1),
    );
    expect(server._generateFieldValue("some.model", "display_name", 1)).not.toBe(
        server._generateFieldValue("some.model", "display_name", 2),
    );
});

test("a 3-argument patch still receives (modelName, fieldName, id)", () => {
    /** @type {[string, string, number][]} */
    const seen = [];
    class Patched extends SampleServer {
        _generateFieldValue(
            /** @type {string} */ modelName,
            /** @type {string} */ fieldName,
            /** @type {number} */ id,
        ) {
            seen.push([modelName, fieldName, id]);
            return super._generateFieldValue(modelName, fieldName, id);
        }
    }
    const server = /** @type {any} */ (new Patched("some.model", { ...FIELDS }));
    server._populateModels();
    const forDisplayName = seen.filter(([, fieldName]) => fieldName === "display_name");
    expect(forDisplayName.length).toBeGreaterThan(0);
    expect(forDisplayName.map(([, , id]) => id)).toEqual(
        forDisplayName.map((_, index) => index + 1),
    );
});
