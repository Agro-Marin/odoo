// @ts-check

/**
 * Unit tests for the useSpecialData hook.
 *
 * The hook arms two loaders over one `loadFn`. `useRecordObserver` answers for
 * the record — its identity and every record value the callback reads — and a
 * second `onWillUpdateProps` answers for the rest of the props, so a `domain`
 * or `context` recomputed by the parent is picked up. The second one must not
 * fire when nothing outside the record moved: RPCs are deduplicated by
 * `specialDataCaches`, but building the domain and the JSON cache key is not.
 *
 * Module under test: fields/relational/special_data.js
 */

import { expect, test } from "@odoo/hoot";
import { animationFrame } from "@odoo/hoot-mock";
import { Component, reactive, useState, xml } from "@odoo/owl";
import {
    defineModels,
    fields,
    models,
    mountWithCleanup,
    onRpc,
} from "@web/../tests/web_test_helpers";
import { useSpecialData } from "@web/fields/relational/special_data";

class Sub extends models.Model {
    _name = "sub";
    name = fields.Char();
    _records = [{ id: 1, name: "s1" }];
}

defineModels([Sub]);

/**
 * Minimal stand-in for what the hook reaches through `props.record`: an `id`,
 * reactive `data`, and the model's shared `specialDataCaches`.
 *
 * @param {number} id
 * @param {Record<string, any>} data
 */
function makeRecord(id, data) {
    return reactive({ id, data, model: { specialDataCaches: new Map() } });
}

/**
 * Mounts a Parent > Child pair where Child loads through `useSpecialData`.
 *
 * @returns {Promise<{ state: any, counts: { loadFn: number, rpc: number } }>}
 */
async function mountSpecialData() {
    const counts = { loadFn: 0, rpc: 0 };
    onRpc("sub", "name_search", () => {
        counts.rpc++;
        return [[1, "s1"]];
    });

    /** @type {any} */
    let state;

    class Child extends Component {
        static template = xml`<span class="child"/>`;
        static props = ["record", "domain"];
        setup() {
            useSpecialData((/** @type {any} */ orm, /** @type {any} */ props) => {
                counts.loadFn++;
                return orm.call("sub", "name_search", ["", props.domain], {});
            });
        }
    }

    class Parent extends Component {
        // `tick` re-renders Parent without changing any prop Child receives:
        // OWL still rebuilds Child's props object and still fires
        // onWillUpdateProps, which is exactly the case the guard is for.
        static template = xml`<span t-esc="state.tick"/><Child record="state.record" domain="state.domain"/>`;
        static components = { Child };
        /** @type {any} */
        static props = [];
        setup() {
            this.state = useState({
                record: makeRecord(1, { foo: 1 }),
                tick: 0,
                domain: "a",
            });
            state = this.state;
        }
    }

    await mountWithCleanup(Parent);
    await animationFrame();
    return { state, counts };
}

test("loads once on mount", async () => {
    const { counts } = await mountSpecialData();
    expect(counts.loadFn).toBe(1);
    expect(counts.rpc).toBe(1);
});

test("a parent re-render that changes no child prop does not reload", async () => {
    // Not the hook's doing: under a *static* prop list OWL compares the listed
    // props and skips the child entirely, so onWillUpdateProps never fires.
    // Contrast with the last test in this file.
    const { state, counts } = await mountSpecialData();
    for (let i = 1; i <= 3; i++) {
        state.tick = i;
        await animationFrame();
    }
    expect(counts.loadFn).toBe(1);
    expect(counts.rpc).toBe(1);
});

test("a props update that changes a loadFn input does reload", async () => {
    const { state, counts } = await mountSpecialData();
    state.domain = "b";
    await animationFrame();
    expect(counts.loadFn).toBe(2);
    // A different domain is a different cache key, so it is a real RPC.
    expect(counts.rpc).toBe(2);
});

test("a new record still reloads", async () => {
    const { state, counts } = await mountSpecialData();
    state.record = makeRecord(2, { foo: 2 });
    await animationFrame();
    expect(counts.loadFn).toBeGreaterThan(1);
});

test("the shape Field actually mounts: t-props with a fresh context each render", async () => {
    // `web.Field` mounts every widget with `t-props="fieldComponentProps"`, and
    // that getter rebuilds `context` (a fresh object from getFieldContext) and
    // `domain` (a fresh closure) on every render. Under a dynamic prop list OWL
    // compares every key by identity, so the child is updated every time --
    // which is the real reason loadFn re-runs, and the reason a prop-identity
    // guard inside the hook cannot help: it compares the very props that churn.
    const counts = { loadFn: 0 };
    onRpc("sub", "name_search", () => [[1, "s1"]]);

    /** @type {any} */
    let state;

    class Child extends Component {
        static template = xml`<span class="child"/>`;
        static props = ["*"];
        setup() {
            useSpecialData((/** @type {any} */ orm) => {
                counts.loadFn++;
                return orm.call("sub", "name_search", ["", []], {});
            });
        }
    }

    class Parent extends Component {
        static template = xml`<span t-esc="state.tick"/><Child t-props="childProps"/>`;
        static components = { Child };
        /** @type {any} */
        static props = [];
        /** @type {any} */
        state;
        setup() {
            this.state = useState({ record: makeRecord(1, { foo: 1 }), tick: 0 });
            state = this.state;
        }
        get childProps() {
            return {
                record: this.state.record,
                context: {}, // fresh object, as getFieldContext returns
                domain: () => /** @type {any[]} */ ([]), // fresh closure, as dynamicInfo.domain is
            };
        }
    }

    await mountWithCleanup(Parent);
    await animationFrame();
    expect(counts.loadFn).toBe(1);

    for (let i = 1; i <= 3; i++) {
        state.tick = i;
        await animationFrame();
    }
    expect(counts.loadFn).toBe(4);
});
