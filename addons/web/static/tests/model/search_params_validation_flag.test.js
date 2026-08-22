// @ts-check

import { after, describe, expect, test } from "@odoo/hoot";
import { Component, xml } from "@odoo/owl";
import { mountWithCleanup, patchWithCleanup } from "@web/../tests/web_test_helpers";
import { SEARCH_KEYS } from "@web/core/constants";
import { clearFeatureFlag, setFeatureFlag } from "@web/core/feature_flags";
import { Model, useModel } from "@web/model/model";
import { SEARCH_PARAMS_SCHEMA } from "@web/model/search_params_schema";

describe.current.tags("headless");

class Probe extends Model {
    async load() {}
}

/**
 * @returns {Promise<string[]>}
 */
async function mountAndCollectWarnings() {
    /** @type {string[]} */
    const warnings = [];
    patchWithCleanup(console, {
        warn: (...args) => warnings.push(args.join(" ")),
    });
    class Host extends Component {
        static template = xml`<div/>`;
        static props = ["*"];
        setup() {
            useModel(Probe, {});
        }
    }
    await mountWithCleanup(Host, { props: { domain: "not-a-domain" } });
    return warnings;
}

test("the flag is read live, not memoised at first use", async () => {
    clearFeatureFlag("search_params_validation");
    after(() => clearFeatureFlag("search_params_validation"));
    patchWithCleanup(odoo, { debug: "" });

    expect(await mountAndCollectWarnings()).toEqual([]);

    setFeatureFlag("search_params_validation", true);
    const warnings = await mountAndCollectWarnings();
    expect(warnings.length).toBe(1);
    expect(warnings[0]).toInclude("[search-params]");

    setFeatureFlag("search_params_validation", false);
    expect(await mountAndCollectWarnings()).toEqual([]);
});

test("debug mode enables it regardless of the flag", async () => {
    clearFeatureFlag("search_params_validation");
    after(() => clearFeatureFlag("search_params_validation"));
    patchWithCleanup(odoo, { debug: "1" });

    const warnings = await mountAndCollectWarnings();
    expect(warnings.length).toBe(1);
    expect(warnings[0]).toInclude("[search-params]");
});

test("SEARCH_KEYS and SEARCH_PARAMS_SCHEMA describe the same set", () => {
    expect([...SEARCH_KEYS].sort()).toEqual(Object.keys(SEARCH_PARAMS_SCHEMA).sort());
});
