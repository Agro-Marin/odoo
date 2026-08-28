// @ts-check

import { after, describe, expect, test } from "@odoo/hoot";
import { Runner } from "@web/../lib/hoot/core/runner";
import { undefineTags } from "@web/../lib/hoot/core/tag";

describe.current.tags("headless");

/**
 * The configurators (`skip`, `only`, ...) are attached with defineProperty, so
 * they are invisible to the checker on the bound `test` / `describe` members.
 */
function makeHeadlessRunner() {
    const runner = new Runner(/** @type {any} */ ({ headless: true }));
    after(() => undefineTags(runner.tags.keys()));
    return {
        runner,
        describe: /** @type {any} */ (runner.describe),
        test: /** @type {any} */ (runner.test),
    };
}

/** @param {Runner} runner */
function suiteNames(runner) {
    return [...runner.suites.values()].map((suite) => suite.name);
}

/** @param {Runner} runner */
function testNames(runner) {
    return [...runner.tests.values()].map((t) => t.name);
}

test("a skipped test declared first does not erase the suite declaring it", () => {
    const { runner, describe: desc, test: t } = makeHeadlessRunner();
    desc("a file suite", () => {
        t.skip("skipped", () => {});
        t("kept", () => {});
        t("also kept", () => {});
    });
    expect(testNames(runner)).toEqual(["kept", "also kept"]);
    expect(suiteNames(runner)).toEqual(["a file suite"]);
});

test("a suite left empty by a skipped test is still erased", () => {
    const { runner, describe: desc, test: t } = makeHeadlessRunner();
    desc("nothing but a skip", () => {
        t.skip("skipped", () => {});
    });
    expect(suiteNames(runner)).toEqual([]);
    expect(testNames(runner)).toEqual([]);
});

test("a skipped test declared first is erased without taking its siblings", () => {
    const { runner, describe: desc, test: t } = makeHeadlessRunner();
    desc("outer", () => {
        desc("inner", () => {
            t.skip("skipped", () => {});
            t("kept", () => {});
        });
    });
    expect(testNames(runner)).toEqual(["kept"]);
    expect(suiteNames(runner)).toEqual(["outer", "inner"]);
});
