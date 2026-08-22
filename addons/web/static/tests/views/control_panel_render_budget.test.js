// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { animationFrame } from "@odoo/hoot-mock";
import { onMounted, onWillRender } from "@odoo/owl";
import {
    defineModels,
    fields,
    models,
    mountView,
    onRpc,
    patchWithCleanup,
    webModels,
} from "@web/../tests/web_test_helpers";
import { Deferred } from "@web/core/utils/concurrency";
import { ControlPanel } from "@web/search/control_panel/control_panel";
import { Layout } from "@web/search/layout";
import { SearchBar } from "@web/search/search_bar/search_bar";
import { SearchBarMenu } from "@web/search/search_bar_menu/search_bar_menu";
import { MultiRecordController } from "@web/views/multi_record_controller";

describe.current.tags("desktop");

class Foo extends models.Model {
    foo = fields.Char();
    int_field = fields.Integer();

    _records = [
        { id: 1, foo: "a", int_field: 1 },
        { id: 2, foo: "b", int_field: 2 },
        { id: 3, foo: "c", int_field: 3 },
    ];
}

defineModels([...Object.values(webModels), Foo]);

const ARCH = `
    <list>
        <field name="foo"/>
        <field name="int_field"/>
    </list>
`;

/**
 * Records an ordered trace of chain renders, mounts, and the model's row count.
 *
 * Every component here is mounted ONCE per view, so a render count above 1 is
 * the same instance rendering again — the distinction a per-label counter such
 * as `useRenderCounter` cannot make on its own, and the reason this suite patches
 * the classes directly.
 */
function instrumentChain() {
    /** @type {string[]} */
    const sequence = [];
    patchWithCleanup(/** @type {any} */ (MultiRecordController).prototype, {
        setup() {
            super.setup();
            onWillRender(() => {
                const model = /** @type {any} */ (this).model;
                sequence.push(`rows=${model?.root?.records?.length}`);
            });
        },
    });
    for (const [name, Cls] of [
        ["MultiRecordController", MultiRecordController],
        ["Layout", Layout],
        ["ControlPanel", ControlPanel],
        ["SearchBar", SearchBar],
        ["SearchBarMenu", SearchBarMenu],
    ]) {
        patchWithCleanup(/** @type {any} */ (Cls).prototype, {
            setup() {
                super.setup();
                onWillRender(() => sequence.push(name));
                onMounted(() => sequence.push(`MOUNTED:${name}`));
            },
        });
    }
    return sequence;
}

/**
 * BUDGET, not a specification, and not a bug report.
 *
 * Opening one list view renders the control-panel chain TWICE. That is the
 * designed cost of `lazy: true`, which `computeModelOptions` sets for any view
 * WITH a control panel (`views/view_utils.js`) and which makes
 * `useModelWithSampleData` skip awaiting the load in `onWillStart`: render the
 * chrome now, re-render when records arrive.
 *
 * What this suite pins is that the payoff is conditional. Both passes complete
 * before anything mounts, so on a fast load nothing paints in between and the
 * first render buys nothing — a mock server and a local page both hide the
 * latency the design exists for. Lowering these numbers is not automatically an
 * improvement; changing them should be a deliberate answer to "when is twice
 * worth it", and this suite makes that change visible.
 */
describe("control-panel chain render budget", () => {
    test("the chain renders twice, and BOTH passes precede every mount", async () => {
        const sequence = instrumentChain();
        await mountView({ resModel: "foo", type: "list", arch: ARCH });
        await animationFrame();

        const renders = sequence.filter((s) => s === "ControlPanel").length;
        expect(renders).toBe(2);

        // The load-bearing half: nothing is mounted between the two passes, so
        // the first render never reaches the DOM *on a load this fast*. The
        // shell-first payoff needs a load slow enough to lose the race with the
        // initial mount fiber, which a mock server never is.
        const firstMount = sequence.findIndex((s) => s.startsWith("MOUNTED:"));
        const lastRender = sequence.lastIndexOf("ControlPanel");
        expect(lastRender).toBeLessThan(firstMount);
    });

    test("the discarded first pass renders an EMPTY model", async () => {
        const sequence = instrumentChain();
        await mountView({ resModel: "foo", type: "list", arch: ARCH });
        await animationFrame();

        // This is why the second pass happens: `lazy: true` means onWillStart
        // does not await the load, so the controller renders before its records
        // exist, they arrive, and OWL re-renders the subtree. Not the search
        // model's UPDATE bus and not an explicit this.render() — both were
        // instrumented and neither fires on this path.
        expect(sequence.filter((s) => s.startsWith("rows="))).toEqual([
            "rows=0",
            "rows=3",
        ]);
    });

    test("SearchBarMenu renders only in the second pass", async () => {
        const sequence = instrumentChain();
        await mountView({ resModel: "foo", type: "list", arch: ARCH });
        await animationFrame();

        // It is unconditional in `search_bar.xml`, so its absence from the first
        // pass says that pass ABORTED partway rather than completing and being
        // superseded.
        expect(sequence.filter((s) => s === "SearchBarMenu").length).toBe(1);
        expect(sequence.filter((s) => s === "SearchBar").length).toBe(2);
    });
});

test("a SLOW load mounts the shell first — the payoff lazy: true exists for", async () => {
    const def = new Deferred();
    onRpc("web_search_read", async () => {
        await def;
    });
    const sequence = instrumentChain();
    const mounting = mountView({ resModel: "foo", type: "list", arch: ARCH });
    for (let i = 0; i < 10; i++) {
        await animationFrame();
    }

    // While the records are still in flight the chain has rendered ONCE, with an
    // empty model, and has MOUNTED. That is the whole point of `lazy: true`: the
    // control panel is on screen before the data exists.
    const beforeData = [...sequence];
    expect(beforeData.filter((e) => e === "ControlPanel").length).toBe(1);
    expect(beforeData.filter((e) => e.startsWith("rows="))).toEqual(["rows=0"]);
    expect(beforeData.some((e) => e === "MOUNTED:ControlPanel")).toBe(true);

    // The first pass also completes here, reaching SearchBarMenu — unlike the
    // fast-load case above, where the data lands mid-render and aborts it.
    expect(beforeData.filter((e) => e === "SearchBarMenu").length).toBe(1);

    def.resolve();
    await mounting;
    await animationFrame();

    // Records arrive: exactly one more pass, and no further mounting.
    const after = sequence.slice(beforeData.length);
    expect(after.filter((e) => e === "ControlPanel").length).toBe(1);
    expect(after.filter((e) => e.startsWith("rows="))).toEqual(["rows=3"]);
    expect(after.some((e) => e.startsWith("MOUNTED:"))).toBe(false);
});
