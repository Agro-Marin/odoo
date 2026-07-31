// @ts-check

/**
 * A sample group's aggregates are computed by one of two paths, chosen by
 * whether the real server returned any groups to hang the sample records on:
 *
 *   - no real groups → ``_mockFormattedReadGroup`` → ``_aggregateFields``
 *   - real groups    → ``_tweakExistingGroups``, which re-derives them inline
 *
 * They must agree. ``_aggregateFields`` rounds every numeric result through
 * ``sanitizeNumber``; the inline branch summed with a bare ``reduce`` and did
 * not, so a float column's group total came back as binary-float noise
 * (``57.97000000000001``) on one path and ``57.97`` on the other, for the same
 * records.
 *
 * Sample data is user-facing — it is what an empty list or kanban renders — so
 * this is a visible artifact, not a test-only concern.
 */

import { describe, expect, test } from "@odoo/hoot";
import { FLOAT_PRECISION } from "@web/model/sample_data";
import { SampleServer } from "@web/model/sample_server";

/** Deterministic subclass, mirroring sample_server.test.js. */
class DeterministicSampleServer extends SampleServer {
    constructor(/** @type {any[]} */ ...args) {
        super(...args);
        this.arrayElCpt = 0;
        this.boolCpt = 0;
        this.subRecordIdCpt = 0;
    }
    _getRandomArrayEl(array) {
        return array[this.arrayElCpt++ % array.length];
    }
    _getRandomBool() {
        return Boolean(this.boolCpt++ % 2);
    }
    _getRandomSubRecordId() {
        return (this.subRecordIdCpt++ % SampleServer.SUB_RECORDSET_SIZE) + 1;
    }
}

const FIELDS = {
    display_name: { string: "Name", type: "char" },
    profession: {
        string: "Profession",
        type: "selection",
        selection: [
            ["gardener", "Gardener"],
            ["brewer", "Brewer"],
        ],
    },
    weight: { string: "Weight", type: "float" },
    age: { string: "Age", type: "integer" },
};

/** How many decimals a number carries. */
function decimals(value) {
    const text = String(value);
    return text.includes(".") ? text.split(".")[1].length : 0;
}

function readGroup(server, aggregates) {
    return server.mockRpc({
        method: "web_read_group",
        model: "hobbit",
        groupBy: ["profession"],
        aggregates,
    });
}

describe("SampleServer aggregate parity across the two group paths", () => {
    test("float sums are rounded on the pure-sample path", async () => {
        const server = new DeterministicSampleServer("hobbit", FIELDS);
        const result = await readGroup(server, ["weight:sum", "__count"]);
        for (const group of result.groups) {
            expect(decimals(group["weight:sum"])).toBeLessThan(FLOAT_PRECISION + 1);
        }
    });

    test("float sums are rounded on the existing-groups path too", async () => {
        const server = new DeterministicSampleServer("hobbit", FIELDS);
        server.setExistingGroups([
            { profession: "gardener", count: 0, __records: [] },
            { profession: "brewer", count: 0, __records: [] },
        ]);
        const result = await readGroup(server, ["weight:sum", "__count"]);
        expect(result.groups).toHaveLength(2);
        for (const group of result.groups) {
            expect(decimals(group["weight:sum"])).toBeLessThan(FLOAT_PRECISION + 1);
        }
    });

    test("integer sums are unaffected on the existing-groups path", async () => {
        const server = new DeterministicSampleServer("hobbit", FIELDS);
        server.setExistingGroups([
            { profession: "gardener", count: 0, __records: [] },
            { profession: "brewer", count: 0, __records: [] },
        ]);
        const result = await readGroup(server, ["age:sum", "__count"]);
        for (const group of result.groups) {
            expect(Number.isInteger(group["age:sum"])).toBe(true);
        }
    });
});
