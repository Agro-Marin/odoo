/** @odoo-module */

import { after, defineTags, describe, expect, test } from "@odoo/hoot";

import { Runner } from "../../core/runner.js";
import { Suite } from "../../core/suite.js";
import { undefineTags } from "../../core/tag.js";
import { parseUrl } from "../local_helpers.js";

const makeTestRunner = () => {
    const runner = new Runner();
    after(() => undefineTags(runner.tags.keys()));
    return runner;
};

describe(parseUrl(import.meta.url), () => {
    test("can register suites", () => {
        const runner = makeTestRunner();
        runner.describe("a suite", () => {});
        runner.describe("another suite", () => {});

        expect(runner.suites).toHaveLength(2);
        expect(runner.tests).toHaveLength(0);
        for (const suite of runner.suites.values()) {
            expect(suite).toMatch(Suite);
        }
    });

    test("can register nested suites", () => {
        const runner = makeTestRunner();
        runner.describe(["a", "b", "c"], () => {});

        expect([...runner.suites.values()].map((s) => s.name)).toEqual(["a", "b", "c"]);
    });

    test("can register tests", () => {
        const runner = makeTestRunner();
        runner.describe("suite 1", () => {
            runner.test("test 1", () => {});
        });
        runner.describe("suite 2", () => {
            runner.test("test 2", () => {});
            runner.test("test 3", () => {});
        });

        expect(runner.suites).toHaveLength(2);
        expect(runner.tests).toHaveLength(3);
    });

    test("should not have duplicate suites", () => {
        const runner = makeTestRunner();
        runner.describe(["parent", "child a"], () => {});
        runner.describe(["parent", "child b"], () => {});

        expect([...runner.suites.values()].map((suite) => suite.name)).toEqual([
            "parent",
            "child a",
            "child b",
        ]);
    });

    test("can refuse standalone tests", async () => {
        const runner = makeTestRunner();
        expect(() =>
            runner.test([], "standalone test", () => {
                expect(true).toBe(false);
            }),
        ).toThrow();
    });

    test("can register test tags", async () => {
        const runner = makeTestRunner();
        runner.describe("suite", () => {
            for (let i = 1; i <= 10; i++) {
                runner.test.tags(`Tag-${i}`);
            }

            runner.test("tagged test", () => {});
        });

        expect(runner.tags).toHaveLength(10);
        expect(runner.tests.values().next().value.tags).toHaveLength(10);
    });

    test("can define exclusive test tags", async () => {
        expect.assertions(3);

        defineTags(
            {
                name: "a",
                exclude: ["b"],
            },
            {
                name: "b",
                exclude: ["a"],
            },
        );

        const runner = makeTestRunner();
        runner.describe("suite", () => {
            runner.test.tags("a");
            runner.test("first test", () => {});

            runner.test.tags("b");
            runner.test("second test", () => {});

            runner.test.tags("a", "b");
            expect(() => runner.test("third test", () => {})).toThrow(
                `cannot apply tag "b"`,
            );

            runner.test.tags("a", "c");
            runner.test("fourth test", () => {});
        });

        expect(runner.tests).toHaveLength(3);
        expect(runner.tags).toHaveLength(3);
    });

    test("headless run refuses an id that matches nothing", () => {
        const runner = new Runner({ headless: true, id: ["deadbeef"] });
        runner.describe("a suite", () => {
            runner.test("a test", () => {});
        });

        expect(() => runner._prepareRunner()).toThrow(
            /no suite or test matches id "deadbeef"/,
        );
    });

    test("headless run names every id that matches nothing", () => {
        const runner = new Runner({ headless: true, id: ["deadbeef", "d15ea5e"] });
        runner.describe("a suite", () => {
            runner.test("a test", () => {});
        });

        expect(() => runner._prepareRunner()).toThrow(
            /no suite or test matches ids "deadbeef", "d15ea5e"/,
        );
    });

    test("headless run accepts an id that matches, and keeps it as a filter", () => {
        const runner = new Runner({ headless: true });
        let suiteId;
        runner.describe("a suite", () => {
            suiteId = runner.suiteStack.at(-1).id;
            runner.test("a test", () => {});
        });
        runner.config.id = [suiteId];
        runner._include(runner.state.includeSpecs.id, [suiteId], 1);

        expect(() => runner._prepareRunner()).not.toThrow();
        expect(runner.hasFilter).toBe(true);
    });

    test("headless run ignores an exclusion that matches nothing", () => {
        const runner = new Runner({ headless: true, id: ["-deadbeef"] });
        runner.describe("a suite", () => {
            runner.test("a test", () => {});
        });

        expect(() => runner._prepareRunner()).not.toThrow();
    });

    test("interactive run drops an id that matches nothing instead of throwing", () => {
        const runner = new Runner({ headless: false, id: ["deadbeef"] });
        runner.describe("a suite", () => {
            runner.test("a test", () => {});
        });

        expect(() => runner._prepareRunner()).not.toThrow();
        expect(runner.hasFilter).toBe(false);
    });

    // Hook timeout. Exercised through `_raceHookTimeout` rather than by starting a
    // nested Runner: nothing in this suite starts one, and a started Runner
    // installs its own global "error"/"unhandledrejection" listeners, which would
    // race with the listeners of the Runner executing these very tests.
    //
    // `config.hookTimeout` is what makes this deterministic AND fast: the timer is
    // the native setTimeout captured before any mock, so a few milliseconds are
    // enough and no clock has to be faked.

    const neverSettles = () => new Promise(() => {});

    test("a before-test hook that outlives the timeout is reported, not discarded", async () => {
        const runner = makeTestRunner();
        runner.config.hookTimeout = 10;

        const error = await runner._raceHookTimeout(
            "before-test",
            { name: "stuck test" },
            neverSettles,
        );

        // The caller skips the test body on a non-null return, so the body never
        // runs against the half-built environment.
        expect(error).not.toBe(null);
        expect(error.message).toInclude("before-test");
        expect(error.message).toInclude("stuck test");
        expect(error.message).toInclude("10 milliseconds");
    });

    test("the hook timeout comes from the config, not a hardcoded value", async () => {
        const runner = makeTestRunner();
        const slowHook = () => new Promise((resolve) => setTimeout(resolve, 40));

        runner.config.hookTimeout = 5;
        expect(
            await runner._raceHookTimeout("before-test", { name: "t" }, slowHook),
        ).not.toBe(null);

        runner.config.hookTimeout = 500;
        expect(
            await runner._raceHookTimeout("before-test", { name: "t" }, slowHook),
        ).toBe(null);
    });

    test("a hook that settles in time reports no error", async () => {
        const runner = makeTestRunner();
        runner.config.hookTimeout = 500;

        expect(
            await runner._raceHookTimeout("after-test", { name: "t" }, async () => {}),
        ).toBe(null);
    });
});
