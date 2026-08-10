// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { animationFrame } from "@odoo/hoot-mock";
import { Component, reactive, useState, xml } from "@odoo/owl";
import { mountWithCleanup } from "@web/../tests/web_test_helpers";
import { disposableEffect, effect, SignalStore } from "@web/core/utils/reactive";

describe.current.tags("headless");

test("SignalStore returns a reactive proxy of itself", () => {
    class Store extends SignalStore {
        n = 1;
    }
    const store = new Store();
    expect(store).toBeInstanceOf(Store);
    const seen = [];
    const tracked = reactive(store, () => seen.push(tracked.n));
    tracked.n;
    store.n = 2;
    expect(seen).toEqual([2]);
});

test("effect fires once eagerly, then on every dependency write", () => {
    const state = reactive({ n: 0 });
    const seen = [];
    effect((s) => seen.push(s.n), [state]);
    expect(seen).toEqual([0]);
    state.n = 1;
    state.n = 2;
    expect(seen).toEqual([0, 1, 2]);
});

test("the effect disposer stops further firing", () => {
    const state = reactive({ n: 0 });
    const seen = [];
    const dispose = effect((s) => seen.push(s.n), [state]);
    state.n = 1;
    dispose();
    state.n = 2;
    expect(seen).toEqual([0, 1]);
});

test("disposableEffect delegates to effect", () => {
    const state = reactive({ n: 0 });
    const seen = [];
    const dispose = disposableEffect((s) => seen.push(s.n), [state]);
    state.n = 1;
    dispose();
    state.n = 2;
    expect(seen).toEqual([0, 1]);
});

// The two tests below pin *why* `@web/core/utils/reactive` exports no
// free-standing computed primitive, and why one cannot be added: OWL keys a
// subscription on the proxy a read travels through, at the moment of the read.
// There is no active-effect stack to consult, so a value derived outside a
// component cannot know who is reading it. See machine_doc_v1/STATE_MANAGEMENT.md.

test("a subscription belongs to the proxy the read went through", async () => {
    const store = new (class extends SignalStore {
        first = "Ada";
        last = "Lovelace";
    })();
    // Closes over the store's own NO_CALLBACK proxy, exactly as a free-standing
    // `derived(() => ...)` helper would.
    const fullName = () => `${store.first} ${store.last}`;

    class Name extends Component {
        static template = xml`<span t-esc="fullName()"/>`;
        static props = {};
        setup() {
            useState(store);
            this.fullName = fullName;
        }
    }

    await mountWithCleanup(Name);
    expect("span").toHaveText("Ada Lovelace");

    store.last = "Byron";
    await animationFrame();
    expect("span").toHaveText("Ada Lovelace", {
        message: "useState subscribes the component, but this read bypassed that proxy",
    });
    expect(fullName()).toBe("Ada Byron", {
        message: "the value is current; only the subscription is absent",
    });
});

test("reading the same state through the component's own proxy does subscribe", async () => {
    const store = new (class extends SignalStore {
        first = "Ada";
        last = "Lovelace";
    })();

    class Name extends Component {
        static template = xml`<span t-esc="fullName"/>`;
        static props = {};
        setup() {
            this.state = useState(store);
        }
        get fullName() {
            return `${this.state.first} ${this.state.last}`;
        }
    }

    await mountWithCleanup(Name);
    expect("span").toHaveText("Ada Lovelace");

    store.last = "Byron";
    await animationFrame();
    expect("span").toHaveText("Ada Byron");
});
