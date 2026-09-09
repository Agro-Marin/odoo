// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { Component, xml } from "@odoo/owl";
import { mountWithCleanup, patchWithCleanup } from "@web/../tests/web_test_helpers";
import { Model, useModelWithSampleData } from "@web/model/model";

describe.current.tags("headless");

class SilentModel extends Model {
    async load() {}
}

class HonestModel extends Model {
    async load() {}
    hasData() {
        return false;
    }
}

/**
 * @param {typeof Model} ModelClass
 * @param {boolean} useSampleModel
 * @returns {Promise<string[]>}
 */
async function mountAndCollectWarnings(ModelClass, useSampleModel) {
    /** @type {string[]} */
    const warnings = [];
    patchWithCleanup(console, {
        warn: (...args) => warnings.push(args.join(" ")),
    });
    class Host extends Component {
        static template = xml`<div/>`;
        static props = ["*"];
        setup() {
            useModelWithSampleData(ModelClass, {});
        }
    }
    await mountWithCleanup(Host, {
        props: {
            useSampleModel,
            resModel: "res.partner",
            fields: { name: { type: "char", string: "Name" } },
        },
    });
    return warnings;
}

test("asking for sample data without overriding hasData says so", async () => {
    const warnings = await mountAndCollectWarnings(SilentModel, true);
    expect(warnings.length).toBe(1);
    expect(warnings[0]).toInclude("SilentModel");
    expect(warnings[0]).toInclude("hasData");
});

test("a model that answers hasData is left alone", async () => {
    expect(await mountAndCollectWarnings(HonestModel, true)).toEqual([]);
});

test("a view that does not ask for sample data is left alone", async () => {
    expect(await mountAndCollectWarnings(SilentModel, false)).toEqual([]);
});
