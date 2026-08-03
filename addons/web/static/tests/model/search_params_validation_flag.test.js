// @ts-check

/**
 * `search_params_validation` gates the warning `useModel` emits when a view
 * hands the model a malformed search param. It is read through `featureFlag`,
 * which resolves the URL and localStorage on EVERY call so it can be flipped
 * from the console without a reload — but the model layer memoised the first
 * answer in a module-global, so `setFeatureFlag` could never turn it on, and
 * the first view mounted in a run fixed the answer for every later test.
 *
 * Driven through the real `useModel` boundary: the gate is module-private and
 * the warning is its only observable effect.
 */

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
 * Mounts a component whose `useModel` receives a malformed `domain` (the schema
 * requires an Array), and returns the warnings that produced.
 *
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

    // First mount with the flag OFF: the call that used to freeze the answer
    // for the rest of the tab.
    expect(await mountAndCollectWarnings()).toEqual([]);

    setFeatureFlag("search_params_validation", true);
    const warnings = await mountAndCollectWarnings();
    expect(warnings.length).toBe(1);
    expect(warnings[0]).toInclude("[search-params]");

    // ...and turning it back off takes effect immediately too.
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
    // `getSearchParams` copies SEARCH_KEYS and nothing else, so the two lists
    // are load-bearing in opposite directions: a key in the schema but not in
    // SEARCH_KEYS is SILENTLY DROPPED at the useModel boundary (the model never
    // sees what the view passed), and a key in SEARCH_KEYS but not in the
    // schema makes the validator report "unknown field" on every single load.
    expect([...SEARCH_KEYS].sort()).toEqual(Object.keys(SEARCH_PARAMS_SCHEMA).sort());
});
