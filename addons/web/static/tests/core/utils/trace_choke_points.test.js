// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import {
    defineModels,
    fields,
    models,
    mountView,
    webModels,
} from "@web/../tests/web_test_helpers";

describe.current.tags("desktop");

class Foo extends models.Model {
    foo = fields.Char();
    int_field = fields.Integer();
    bar = fields.Boolean();

    _records = [
        { id: 1, foo: "a", int_field: 1, bar: true },
        { id: 2, foo: "b", int_field: 2, bar: false },
    ];
}

defineModels([...Object.values(webModels), Foo]);

const TWO_FIELD_ARCH = `
    <list>
        <field name="foo"/>
        <field name="int_field"/>
    </list>
`;

const THREE_FIELD_ARCH = `
    <list>
        <field name="foo"/>
        <field name="int_field"/>
        <field name="bar"/>
    </list>
`;

/**
 * Arms the structured sink, runs `body`, and returns what was recorded.
 *
 * The sink lives on globalThis, so it is reset before and disarmed after —
 * otherwise one test's counts are visible to the next.
 *
 * @param {() => Promise<void>} body
 * @returns {Promise<Record<string, number>>}
 */
async function readTrace(body) {
    const globals = /** @type {any} */ (globalThis);
    const priorFlag = globals.__odooTrace;
    const priorCounts = globals.__odooTraceCounts_;
    globals.__odooTrace = true;
    globals.__odooTraceReset();
    try {
        await body();
        return globals.__odooTraceStats();
    } finally {
        globals.__odooTrace = priorFlag;
        globals.__odooTraceCounts_ = priorCounts;
    }
}

describe("choke points fire on a real view mount", () => {
    test("view.load and view.loadViews record once per mounted view", async () => {
        const trace = await readTrace(async () => {
            await mountView({ type: "list", resModel: "foo", arch: TWO_FIELD_ARCH });
        });
        expect(trace["view.load"]).toBe(1);
        expect(trace["view.loadViews"]).toBe(1);
    });

    test("field.resolve records once per field node in a two-field arch", async () => {
        const trace = await readTrace(async () => {
            await mountView({ type: "list", resModel: "foo", arch: TWO_FIELD_ARCH });
        });
        expect(trace["field.resolve"]).toBe(2);
    });

    test("field.resolve scales with the arch: three field nodes, three resolves", async () => {
        const trace = await readTrace(async () => {
            await mountView({ type: "list", resModel: "foo", arch: THREE_FIELD_ARCH });
        });
        expect(trace["field.resolve"]).toBe(3);
    });

    test("model.load records the record fetch behind the view", async () => {
        const trace = await readTrace(async () => {
            await mountView({ type: "list", resModel: "foo", arch: TWO_FIELD_ARCH });
        });
        expect(trace["model.load"]).toBe(1);
    });

    test("every started service also reports started, and none fails", async () => {
        const trace = await readTrace(async () => {
            await mountView({ type: "list", resModel: "foo", arch: TWO_FIELD_ARCH });
        });
        // The absolute count moves whenever a service is added, so the invariant
        // is the one worth pinning: a service that enters a wave must resolve.
        expect(trace["service.start"]).toBeGreaterThan(0);
        expect(trace["service.started"]).toBe(trace["service.start"]);
        expect(trace["service.failed"]).toBe(undefined);
    });
});

describe("what this harness can and cannot observe", () => {
    test("component.mount does not fire: the test harness builds its own App", async () => {
        // mountWithCleanup constructs `new App(...)` directly rather than going
        // through env.js's mountComponent, so the component probe is a
        // production-only reading. Asserting its ABSENCE here means the day the
        // harness is changed to share that path, this test says so instead of
        // the gap being rediscovered from scratch.
        const trace = await readTrace(async () => {
            await mountView({ type: "list", resModel: "foo", arch: TWO_FIELD_ARCH });
        });
        expect(trace["component.mount"]).toBe(undefined);
    });

    test("rpc.request DOES fire: the mock server dispatches through rpcBus", async () => {
        // Recorded as a correction. While both listeners in core/network/rpc.js
        // guarded on rpcLog.enabled() -- the console gate -- this read undefined,
        // and the obvious reading was "the mock server replaces the rpc layer".
        // It does not: it dispatches RpcEvent.REQUEST like the real one, and the
        // guard was simply blind to the sink. Widening it to active() made the
        // traffic visible in BOTH harnesses.
        const trace = await readTrace(async () => {
            await mountView({ type: "list", resModel: "foo", arch: TWO_FIELD_ARCH });
        });
        expect(trace["model.load"]).toBe(1);
        expect(trace["rpc.request"]).toBeGreaterThan(0);
    });
});

describe("the sink stays off unless armed", () => {
    test("a mount with __odooTrace unset records nothing", async () => {
        const globals = /** @type {any} */ (globalThis);
        const priorFlag = globals.__odooTrace;
        const priorCounts = globals.__odooTraceCounts_;
        globals.__odooTrace = false;
        globals.__odooTraceReset();
        try {
            await mountView({ type: "list", resModel: "foo", arch: TWO_FIELD_ARCH });
            expect(globals.__odooTraceStats()).toEqual({});
        } finally {
            globals.__odooTrace = priorFlag;
            globals.__odooTraceCounts_ = priorCounts;
        }
    });
});
